# Campus Lost & Found

Flask + Supabase (Postgres, Auth, Storage) + Tailwind via CDN.

```
campus-lost-and-found/
├── app.py
├── supabase_setup.sql
├── requirements.txt
├── .env.example
└── templates/  base, login, signup, dashboard, post_item
```

## 1. Set up Supabase

1. Create a project at https://supabase.com.
2. Open **SQL Editor > New query**, paste all of `supabase_setup.sql`, and click **Run**.
   This creates `profiles`, `items`, a signup trigger, RLS policies, and the two storage buckets
   `item-photos` and `proof-photos`.
3. **Authentication > Providers > Email**: for local testing, turn **off** "Confirm email" so new
   students can log in right after signing up. (If you leave it on, the app tells them to confirm via email first.)
4. **Project Settings > API**: copy the Project URL, the `anon` (or publishable) key, and the
   `service_role` (or secret) key.

## 2. Configure environment variables

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Fill in `.env`:

| Variable | Where it comes from |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_ANON_KEY` | anon / publishable key (used only for login and signup) |
| `SUPABASE_SERVICE_KEY` | service_role / secret key (server only, never share or commit) |
| `FLASK_SECRET_KEY` | any long random string |

## 3. Install and run

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The terminal prints two addresses, for example:

```
On this computer:  http://localhost:5000
On your phone:     http://192.168.1.23:5000   (same Wi-Fi)
```

## 4. Open it on your phone

1. Connect the phone to the **same Wi-Fi** as your computer.
2. Open the "On your phone" address in the phone's browser.
3. If it doesn't load:
   - **Windows**: allow Python through Windows Defender Firewall when prompted (Private networks), or
     add an inbound rule for TCP port 5000.
   - **macOS**: allow incoming connections for Python when prompted.
   - Some campus or public Wi-Fi blocks device-to-device traffic ("client isolation"). Use a phone
     hotspot, or connect both devices to your home network.

## How it works

- **Auth**: Supabase Auth handles passwords. Flask keeps the logged-in student in a signed session cookie.
- **Profiles**: a database trigger creates a `profiles` row (full name + email) on signup.
- **Posting**: the server validates the form, uploads the item photo to `item-photos` and the proof photo
  to `proof-photos` (JPG/PNG/WebP, max 5 MB each), saves only the public URLs in `items`, and deletes the
  uploaded files if the database insert fails.
- **Ownership**: only the poster can mark a post resolved or delete it (the server checks `user_id`).

## Important: the proof photo is "public" by design of this brief

You asked for public URLs to be stored, so the proof bucket is public. The app never shows other students
the proof photo, but **anyone who obtains the URL can open it**. File names are random, which helps, but
for real campus use you should harden it:

1. In the SQL script set `proof-photos` to `public = false`.
2. Store the file path instead of the URL in `proof_url`.
3. Generate a short-lived link when needed with
   `db.storage.from_("proof-photos").create_signed_url(path, 60)`.

## Other notes

- `debug=True` is for local development only. Before deploying, run behind gunicorn with debug off.
- Add HTTPS and `SESSION_COOKIE_SECURE=True` when deploying.
- Never expose `SUPABASE_SERVICE_KEY` in templates or client-side code.
