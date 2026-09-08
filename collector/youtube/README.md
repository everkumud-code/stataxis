# YouTube collector

The first collector uses registered YouTube channel IDs and each channel's system-generated uploads playlist. It then batches video IDs into `videos.list` requests to retrieve statistics and live-streaming fields.

This deliberately avoids making YouTube search the core discovery mechanism. YouTube documents the uploads playlist as the channel's uploaded-video collection, and `playlistItems.list` has a 1-unit quota cost. The video resource exposes `statistics` and `liveStreamingDetails`, including `concurrentViewers` when YouTube provides it.

## Local smoke test

1. Copy `.env.example` to `.env`.
2. Put the API key only in `.env`.
3. Copy `config/channels.example.json` to `config/channels.json` and replace the placeholder with a verified channel ID.
4. Run:

```bash
python -m collector.main --channels config/channels.json
```

Never commit `.env` or a real API key.
