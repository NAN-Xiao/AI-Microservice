# ComfyUI Cleanup Delete Route

This plugin does not add any workflow nodes.

It only registers a backend route:

- `POST /delete`

Request body:

```json
{
  "filename": "example.png",
  "subfolder": "",
  "type": "output"
}
```

Supported `type` values:

- `input`
- `output`
- `temp`

Install:

1. Copy this whole folder into `ComfyUI/custom_nodes/`
2. Restart ComfyUI
3. Test with:

```bash
curl -X POST http://127.0.0.1:8188/delete \
  -H "Content-Type: application/json" \
  -d "{\"filename\":\"example.png\",\"subfolder\":\"\",\"type\":\"output\"}"
```
