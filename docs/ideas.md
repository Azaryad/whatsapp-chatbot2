# Ideas for Future Consideration

These were noted during MVP build but deliberately excluded from scope.

- **Telegram/email fallback for Michel** — currently WhatsApp only; hook exists in `dispatch.py:_notify_michel`
- **Driver rating / performance score** — track acceptance rate, punctuality, customer feedback to improve Claude ranking
- **Multi-language driver messages** — currently Hebrew only; could detect driver language preference and generate in Russian/Arabic/English
- **Booking.com / HolidayTaxis status sync** — `POST /reportstatus` is available in supplier API; wire it to trip lifecycle events
- **Web push notifications for dispatcher** — replace poll-based dashboard refresh with WebSocket or SSE
- **Driver self-registration portal** — form that creates a driver record and pushes to supplier API
- **Postgres migration** — SQLAlchemy is already Postgres-ready; just swap `DATABASE_URL`
- **Rate limiting on `/api/trips/ingest`** — add API key auth so only the main OS can push trips
- **Conflict detection improvement** — currently uses fixed 90-min buffer; improve with actual trip duration from Maps API
- **Shabbat exact times** — integrate `hdate` library for precise astronomical sunset per date/location
