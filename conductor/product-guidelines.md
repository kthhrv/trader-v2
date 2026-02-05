# Product Guidelines

## Documentation & Communication
- **Tone:** Formal and Precise. Internal documentation and logs must prioritize technical accuracy and use unambiguous terminology.
- **Style:** Code should be self-documenting through clear naming and modular structure. Docstrings should be used for public interfaces, and comments should focus on explaining "why" for complex logic rather than "what".

## Error Handling & Reliability
- **Philosophy:** Fail-Fast and Notify. The system must halt execution on critical errors to prevent incorrect trade execution. Manual intervention is required for recovery after a critical failure.
- **Logging:** All state transitions and critical decisions must be logged with enough detail to reconstruct the system's state during post-mortem analysis.

## Development Standards
- **Testability:** As a core requirement, all new features must be accompanied by comprehensive tests. The FSM approach should be leveraged to enable deterministic testing of trade states.
- **Modularity:** Adhere to the existing adapter-based architecture to ensure components (e.g., data sources, execution clients) remain decoupled and interchangeable.
