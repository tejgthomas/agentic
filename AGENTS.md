## Execution & Scope
* Craftsman's Creed: Write flat, functional, concise, idiomatic, ultra-performant code, in absolute terms, without enterprise abstractions, dependency injection, or wrappers (DTO, ORM). Static peer-review before output.
* View Forest Holistically: State assumptions explicitly. If multiple completions exist, present them - don't pick silently. Look beyond the direct question at the broader intent. If a simpler, cleaner, more holistic, and more performant alternative exists, present it and briefly explain the structural why.
* High-Density Output: Deliver concise, actionable edits. Eliminate conversational filler or pleasantries. Silently fix syntax and typos. Omit cosmetic diff clutter. Once a design or code pattern choice is made, prefer it for the rest of the work session. After every choice confirmation, recap any unresolved issues from prior turns.
* System 2 Planning: Map invariants, edge cases, and dependencies. Peer-review statically before coding. Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.
* Strict Scoping: Limit analysis to assigned task files. Step outside strictly to resolve direct, uncompiled dependencies, then return immediately. No abstractions for single-use code. Every changed line should trace directly to the request. Surface dead code and adjacent code that contradicts requested change - don't auto-edit.

## Environment & Tooling
* Target: Back end bare-metal Ubuntu deployment, local development may be on a different platform not set up for deployment. Never suggest Docker or other containers.
* Cutting-Edge Platforms: Target current course toolchains for Android/Kotlin and Python/Starlette.

## Universal Language Compliance
* Expressions Over Statements: Prefer direct assignment over multi-line if-else when readability is not harmed.
* Modern Async & Streams: Use native structured concurrency and event streams over legacy thread queues.
* State Mechanics: Prefer native immutable/reactive state flows.

## Style & Documentation
* Semantic Variables: Name elements by functional, system-level purpose. Match existing style.
* Strategic Comments: Document why an algorithm exists. Never comment on what syntax does.
