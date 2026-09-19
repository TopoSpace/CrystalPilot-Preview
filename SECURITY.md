# Security

CrystalPilot is a local application. The service binds to `127.0.0.1` and
rejects requests whose `Host` or `Origin` is not local; it is not designed to be
exposed to a network. Provider API keys are read on demand from files under
`secrets/`, which git ignores, and are handed to the kernel through its auth
command. They are not written to the configuration file, to project folders or
to transcripts.

If you believe you have found a vulnerability, please report it through
GitHub's private vulnerability reporting on this repository rather than in a
public issue. Include the commit you are running, the platform, and the steps
needed to reproduce the behaviour.
