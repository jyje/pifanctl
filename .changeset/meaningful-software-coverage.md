---
"pifanctl": patch
"pifanctl-operator": patch
---
Fix(testing): verify software safety contracts with meaningful full coverage

Exercise real model, planner, control, CLI, file IO and HTTP behaviors. Restrict
doubles to hardware, Kubernetes/remote IO failures and controlled scheduling;
replace GPIO reader tests that bypassed constructors. Simplify an unreachable
operator owner fallback and expand inline safety checks without changing their
behavior. Use consistent C tracing and require exact full line/branch coverage
in local CI gates and Codecov. App and operator chart advance together to 1.2.1.
Software coverage does not certify physical PWM, RPM, wiring or cooling behavior.
