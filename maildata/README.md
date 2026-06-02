# maildata — drop your email archive here

Put the **`.mbx` / `mbox`** files (or per-folder mailbox files) in this directory.
The ingest pipeline and the gateway container mount it **read-only** at `/data/mail`.

```
email-mcp-gateway/
└── maildata/            ← host path (this dir)   →  /data/mail  (in container, READ-ONLY)
    ├── inbox.mbx
    ├── sent.mbx
    └── archive/...      ← nested folders are fine
```

Notes
- Read-only by design: the gateway never modifies your mail.
- Index/embeddings are written elsewhere (`../index`, read-write), not here.
- ~25 GB expected; host has ~325 GB free, so headroom is fine.
- After dropping files, run the ingest job (P1) to build the LanceDB index.
