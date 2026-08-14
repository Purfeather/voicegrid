# Legacy desktop host

This package contains the pre-startup-optimization desktop host retained only
for internal rollback. The supported compatibility entry point remains:

```text
pythonw -m desktop.host_legacy
```

New native-host work belongs in `desktop/native`; do not add features here.

