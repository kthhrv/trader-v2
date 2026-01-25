import redis
import json
import time


def inject_spike():
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    epic = "IX.D.FTSE.DAILY.IP"
    base_price = 8000.0

    print(f"Injecting base ticks for {epic}...")
    for i in range(10):
        tick = {
            "type": "price_update",
            "epic": epic,
            "bid": base_price + (i * 0.1),
            "offer": base_price + (i * 0.1) + 2.0,
            "time": "12:00:00",
        }
        r.publish("market_data", json.dumps(tick))
        time.sleep(0.1)

    print("BOOM! Injecting SPIKE (+1.25%)...")
    spike_tick = {
        "type": "price_update",
        "epic": epic,
        "bid": base_price * 1.0125,
        "offer": (base_price * 1.0125) + 2.0,
        "time": "12:00:01",
    }
    r.publish("market_data", json.dumps(spike_tick))
    print("Spike injected. Check trader-watcher logs.")


if __name__ == "__main__":
    inject_spike()
