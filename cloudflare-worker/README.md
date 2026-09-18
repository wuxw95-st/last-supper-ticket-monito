# Cloudflare availability probe

This Worker performs a read-only diagnostic against the official Vivaticket page.

It does not send notifications, place orders, store credentials, or run on a schedule.
After deployment, open the generated workers.dev URL and inspect the JSON result.
Only enable the one-minute schedule after the result reports `"ok": true`.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/wuxw95-st/last-supper-ticket-monito/tree/main/cloudflare-worker)
