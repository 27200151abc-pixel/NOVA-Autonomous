# NOVA plugins

Drop owner-authored Python plugin files in this folder. Each plugin must define:

- `PLUGIN`: a manifest with a unique `name`, human-readable `description`, and JSON Schema `parameters`.
- `run(arguments)`: a function returning a JSON-serializable result.

Then add the plugin name to `enabled_plugins` in `nova/policy.json`.

**Trust boundary:** enabling a Python plugin executes its code inside the NOVA server process with that process's operating-system permissions. Only enable code you wrote or reviewed. For untrusted third-party plugins, use a separate restricted process/container before enabling them. Plugins marked in `approval_required` are currently refused; an approval queue is a future feature.
