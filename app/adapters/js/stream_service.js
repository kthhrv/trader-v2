const ls = require('lightstreamer-client');

// Basic logging to stderr for Python to capture
function log_error(message) { console.error("[NODE_STREAM_ERROR] " + message); }
function log_info(message) { console.log("[NODE_STREAM_INFO] " + message); }
function log_data(data) { console.log(JSON.stringify(data)); } // JSON to stdout

log_info("Node.js Stream Service starting...");

// --- Configuration from CLI arguments ---
const args = process.argv.slice(2); // Remove 'node' and 'script_name.js'

const cst = args[0];
const xst = args[1];
const account_id = args[2];
const epic = args[3];
const ls_endpoint = args[4] || "https://demo-apd.marketdatasystems.com";

if (!cst || !xst || !account_id || !epic) {
    log_error("Missing required arguments: CST, XST, Account ID, and Epic.");
    process.exit(1);
}

log_info(`Connecting to LS: ${ls_endpoint}, Account: ${account_id}, Epic: ${epic}`);

// --- Lightstreamer Client Setup ---
const client = new ls.LightstreamerClient(ls_endpoint, "DEFAULT");

client.connectionDetails.setUser(account_id);
client.connectionDetails.setPassword(`CST-${cst}|XST-${xst}`);

// --- Liveness Heartbeat ---
// If no price update arrives for HEARTBEAT_TIMEOUT_MS, assume the connection is dead.
const HEARTBEAT_TIMEOUT_MS = 120_000; // 2 minutes
const RECOVERY_TIMEOUT_MS = 60_000;   // 1 minute max in WILL-RETRY/TRYING-RECOVERY
let lastTickTime = Date.now();
let recoveryTimer = null;

function startRecoveryTimer(status) {
    if (recoveryTimer) return; // Already ticking
    log_info(`Starting ${RECOVERY_TIMEOUT_MS/1000}s recovery timer (status: ${status})`);
    recoveryTimer = setTimeout(() => {
        log_error(`Recovery timeout expired in state: ${status}. Exiting.`);
        process.exit(1);
    }, RECOVERY_TIMEOUT_MS);
}

function clearRecoveryTimer() {
    if (recoveryTimer) {
        clearTimeout(recoveryTimer);
        recoveryTimer = null;
    }
}

client.addListener({
  onStatusChange: function(newStatus) {
    log_info("[LS Status]: " + newStatus);

    if (newStatus.startsWith("CONNECTED:")) {
        clearRecoveryTimer();
    } else if (newStatus === "DISCONNECTED") {
        log_error("Lightstreamer disconnected. Exiting.");
        process.exit(1);
    } else if (newStatus === "STALLED") {
        log_error("Lightstreamer stalled (no data from server). Exiting.");
        process.exit(1);
    } else if (newStatus.startsWith("DISCONNECTED:WILL-RETRY") || newStatus.startsWith("DISCONNECTED:TRYING-RECOVERY")) {
        startRecoveryTimer(newStatus);
    }
  },
  onServerError: function(code, msg) {
    log_error(`[LS Server Error]: ${code} - ${msg}`);
  },
  onLoadError: function(url) {
    log_error(`[LS Load Error]: ${url}`);
  }
});

client.connect();

// Heartbeat check: exit if no ticks received for HEARTBEAT_TIMEOUT_MS.
// Disabled on weekends (Sat ~05:00 UTC to Sun ~22:00 UTC) when IG sends no ticks.
setInterval(() => {
    const now = new Date();
    const day = now.getUTCDay();    // 0=Sun, 6=Sat
    const hour = now.getUTCHours();

    // Weekend quiet window: Friday 22:00 UTC -> Sunday 22:00 UTC
    const isWeekendQuiet = (day === 5 && hour >= 22) || (day === 6) || (day === 0 && hour < 22);
    if (isWeekendQuiet) {
        lastTickTime = Date.now(); // Keep resetting so we don't fire on Monday
        return;
    }

    const elapsed = Date.now() - lastTickTime;
    if (elapsed > HEARTBEAT_TIMEOUT_MS) {
        log_error(`No ticks received for ${Math.round(elapsed/1000)}s. Exiting.`);
        process.exit(1);
    }
}, 30_000);

// --- Subscription 1: Market Data (MERGE) ---
// IG's LS adapter uses MARKET:<epic>; the older L1:<epic> group is now
// rejected with "21 Invalid group".
const priceSub = new ls.Subscription("MERGE", [`MARKET:${epic}`], ["BID", "OFFER", "UPDATE_TIME", "MARKET_STATE"]);

priceSub.addListener({
  onItemUpdate: function(update) {
    const bidRaw = update.getValue("BID");
    const offerRaw = update.getValue("OFFER");
    const update_time = update.getValue("UPDATE_TIME");
    const market_state = update.getValue("MARKET_STATE");

    if (bidRaw && offerRaw) {
        lastTickTime = Date.now();
        const bid = parseFloat(bidRaw);
        const offer = parseFloat(offerRaw);

        if (bid <= 0 || offer <= 0) {
            log_error(`Invalid Price Detected! Raw BID: "${bidRaw}", Raw OFFER: "${offerRaw}", Epic: ${epic}`);
        }

        log_data({
            type: "price_update",
            epic: epic,
            bid: bid,
            offer: offer,
            time: update_time,
            market_state: market_state
        });
    }
  },
  onSubscription: function() {
    log_info(`Subscribed to Price: ${epic}`);
  },
  onSubscriptionError: function(code, msg) {
    log_error(`[Price Subscription Error]: ${code} - ${msg}`);
  }
});

client.subscribe(priceSub);

// --- Subscription 2: Trade Updates (DISTINCT) ---
// Subscribing to TRADE:{account_id} to receive CONFIRMS and OPU (Open Position Updates)
const tradeSub = new ls.Subscription("DISTINCT", [`TRADE:${account_id}`], ["CONFIRMS", "OPU"]);
tradeSub.setRequestedSnapshot("yes");

tradeSub.addListener({
  onItemUpdate: function(update) {
    const confirms = update.getValue("CONFIRMS");
    const opu = update.getValue("OPU");
    
    // We log anything significant.
    // 'CONFIRMS' usually contains JSON string about recent trade success/fail.
    // 'OPU' contains JSON string about position status changes.
    
    if (confirms) {
        log_data({
            type: "trade_update",
            subtype: "confirms",
            payload: confirms
        });
    }
    if (opu) {
         log_data({
            type: "trade_update",
            subtype: "opu",
            payload: opu
        });
    }
  },
  onSubscription: function() {
     log_info(`Subscribed to Trades: TRADE:${account_id}`);
  },
  onSubscriptionError: function(code, msg) {
    log_error(`[Trade Subscription Error]: ${code} - ${msg}`);
  }
});

client.subscribe(tradeSub);

// Process kept alive by the heartbeat setInterval above.
