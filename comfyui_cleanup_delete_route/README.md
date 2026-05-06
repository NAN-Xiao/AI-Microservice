# ComfyUI Cleanup Delete Route

This plugin does not add any workflow nodes.

It only registers backend routes:

- `POST /delete`
- `POST /delete-directory`

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

Directory cleanup:

```json
{
  "subfolder": "seethrough/requests/request-id",
  "type": "output"
}
```

The route deletes only `seethrough/requests/*` directories inside ComfyUI `input`, `output`, or `temp` roots and refuses the base directory itself.

Install:

1. Copy this whole folder into `ComfyUI/custom_nodes/`
2. Restart ComfyUI
3. Test with:

```bash
curl -X POST http://127.0.0.1:8188/delete \
  -H "Content-Type: application/json" \
  -d "{\"filename\":\"example.png\",\"subfolder\":\"\",\"type\":\"output\"}"

curl -X POST http://127.0.0.1:8188/delete-directory \
  -H "Content-Type: application/json" \
  -d "{\"subfolder\":\"seethrough/requests/example\",\"type\":\"output\"}"
```
