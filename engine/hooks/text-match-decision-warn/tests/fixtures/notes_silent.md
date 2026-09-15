# Repair notes

The worker marked the task as infra when the signature appeared in error output.

```python
if any(signature in error for signature in SIGNATURES):
    return "infra"
```
