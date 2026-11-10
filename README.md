# mykid-cal

A tiny proxy that serves a **cleaned-up copy of your [MyKid](https://mykid.no) kindergarten calendar**, so you can subscribe to it from iOS, Google Calendar, Home Assistant etc. without the noise.

MyKid's own iCal feed lists every weekly routine (gym, arts and crafts, outdoor play, …), which drowns out the few events you actually care about: closures, parties, parent meetings and holidays. In a typical feed, about 90% of events are routines.

What it does:

- **Drops weekly routines.** Any event title that shows up in 3 or more different weeks in the feed is treated as a routine and removed. New routines get filtered automatically, without any config. Titles are compared loosely, so "Gymrom gruppe 1" and "Gymrom gr. 1" count as the same.
- **Merges multi-day closures.** Consecutive all-day events with the same title become one event, even across weekends and public holidays. For example, "Juleferie" on six separate weekdays becomes one event from 21 to 30 December.
- **Caches** each feed for 15 minutes, and serves the last good copy if MyKid is down.

No dependencies beyond the Python 3.12+ standard library.

## Getting your feed link

1. Log in at [mykid.no](https://mykid.no) and open **Kalender**.
2. Copy the link from the box at the top right (`https://mykid.no/calendar/mykid_calendar.php?uid=…`).
3. The part after `uid=` is your feed's secret. Anyone with it can read your kid's calendar, so treat it like a password.

## Usage

Run it:

```sh
python app.py                    # listens on $PORT, default 5000
# or
docker build -t mykid-cal . && docker run -p 5000:5000 mykid-cal
```

Then subscribe to:

```
https://<your-host>/<your-mykid-uid>.ics
```

On iOS, go to Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → **Add Subscribed Calendar**.

Serve it over HTTPS (e.g. behind a reverse proxy) so the uid isn't sent in plain text.

## Configuration

All settings are optional environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5000` | Port to listen on |
| `ALLOW_ANY_UID` | `1` | Serve `/<uid>.ics` for any MyKid uid. Set to `0` to only allow the token route below. |
| `MYKID_UID` + `ACCESS_TOKEN` | – | Also serve `MYKID_UID`'s feed at `/<ACCESS_TOKEN>.ics`, so the link you share doesn't contain the MyKid uid itself. |
| `RECURRING_WEEKS` | `3` | A title seen in at least this many distinct weeks counts as a routine |
| `MERGE_GAP_DAYS` | `4` | All-day runs at most this many days apart are merged |
| `CACHE_SECONDS` | `900` | How long a fetched feed is reused |
| `ALWAYS_KEEP` | – | Regex (case-insensitive) of titles to always keep, even if recurring |
| `ALWAYS_DROP` | – | Regex (case-insensitive) of titles to always drop |

See [`.env.example`](.env.example).

## Privacy notes

- The app logs only status codes for feed requests, never the uid or token. A reverse proxy in front of it will usually log full URLs, uid included, so lock down or trim those logs.
- With `ALLOW_ANY_UID=1`, anyone who knows your host can use it to clean their own MyKid feed. Uids are long and random, so they can't be guessed, but set `ALLOW_ANY_UID=0` if you want it private.

## Tests

```sh
python -m unittest
```

## Disclaimer

This is an unofficial project, not affiliated with MyKid AS. It only reads the iCal export that MyKid offers to parents.
