# Your own Google client ID

Nimbus Drive signs in to Google through rclone, and every app that signs in to Google needs an
OAuth **client ID**. rclone's shared one is being retired by Google during 2026; connections
that still use it stop working at that point. So you create your own, once.

**Plan for 30–60 minutes the first time.** Google's console is slow to click through, it renames
its pages often, and one step (publishing) has a catch described below. It is free.

It also pays off right away: with the shared ID, Google throttles requests from everyone
sharing it. With your own, listing a large Drive folder dropped from about 50 seconds to about
1 second in our tests, and the `rateLimitExceeded` errors disappeared.

## Before you start: Testing or published?

Your app stays in one of two states. Decide now which one you want.

| | **Testing** (easy) | **Published** (one more step) |
|---|---|---|
| Setup | Steps 1–6 below | Steps 1–7 below |
| Extra requirement | none | A home page and a privacy policy on a domain you own |
| Sign-in lasts | **7 days**, then Google drops it and Google Drive stops connecting until you sign in again | Until you revoke it |

In **Testing**, signing in again takes one click: *Nimbus Drive → Account → Reconnect* (the same
client ID and secret stay). It is fine to start with Testing and publish later.

**Google Workspace (company) accounts:** choose *Internal* in step 2. Internal apps never expire
and need no publishing — skip step 7.

## Steps

The console is at <https://console.cloud.google.com/>. Use any Google account; it does not have to
be the one that owns your Drive.

1. **Project and API.** At the top, pick or create a project (name: e.g. `nimbus-drive`). Then
   go to *APIs & Services → Library*, search for **Google Drive API** and press **Enable**.

2. **Consent screen.** Go to *APIs & Services → OAuth consent screen* (newer consoles call this
   *Google Auth Platform*) and press **Get started**:
   - App name: anything that does **not** contain "Google" — e.g. `nimbus-drive-yourname`.
     Google rejects names with its product names.
   - User support email: yours.
   - Audience: **External** (or *Internal* for Workspace, see above).
   - Contact email: yours. Accept the policy and press **Create**.

3. **Scopes.** Open *Data Access → Add or remove scopes*. Paste these into *Manually add
   scopes*, press **Add to table**, then **Update** and **Save**:

   ```
   https://www.googleapis.com/auth/drive
   https://www.googleapis.com/auth/docs
   https://www.googleapis.com/auth/drive.metadata.readonly
   ```

4. **Yourself as a test user.** Open *Audience → Test users → Add users*, enter the Gmail
   address of the Drive you will use, **Save**. (Needed while the app is in Testing; harmless
   later.)

5. **The client.** Open *Clients* (or *Credentials*) → **Create client** → type
   **Desktop app** → **Create**. Copy the **Client ID** and **Client secret**. Do not use the
   *Create credentials* wizard on the Credentials page; it asks unrelated questions.

6. **Connect Nimbus Drive.** In Nimbus Drive open *Account → Reconnect with your own client ID*
   (or *Connect another account* for a new connection), paste the ID and secret and press
   **Sign in with browser**. Google then warns:

   > Google hasn't verified this app

   That is expected for your own app. Press **Advanced → Go to nimbus-drive-yourname (unsafe)**,
   tick the permission boxes and **Continue**. Done — you are in Testing mode.

7. **Optional: publish, so the sign-in does not expire.** Open *Audience* → **Publish app**.

   If the button is greyed out or Google keeps your changes empty, it wants a home page and a
   privacy policy on a domain **you own**. `github.com` does **not** count (you do not own it),
   and Google silently drops it. Free ways that work:

   - **GitHub Pages:** create a repository named `<your-github-name>.github.io` with an
     `index.html` saying "Personal Google Drive client for my own use" and a `privacy.html` saying
     "This app only accesses my own Google Drive from my own computer. No data is collected or
     shared." Your domain is then `<your-github-name>.github.io`.
   - **A domain you already have**, with the same two pages.

   Then in *Branding*: fill **Application home page** and **Application privacy policy link**
   with those two pages, add the domain under **Authorized domains**, **Save**. Go back to
   *Audience* and press **Publish app → Confirm**.

   Google may say the app "needs verification". You do **not** have to submit it: personal apps
   with fewer than 100 users work unverified; you only see the warning from step 6 when signing
   in. After publishing, sign in once more (*Account → Reconnect*) so the new, non-expiring
   sign-in replaces the 7-day one.

## Troubleshooting

- **`access_denied` / "app has not completed the Google verification process"** — your Google
  account is not in *Test users* (step 4) while the app is in Testing.
- **Google Drive stops connecting after a week** — the app is in Testing. Reconnect
  (*Account → Reconnect*), or publish it (step 7).
- **`invalid_client`** — the ID or secret was pasted with a space or from a different project.
- **"Branding" fields are empty after saving** — the home page or privacy link is on a domain
  you do not own (for example `github.com`). Use GitHub Pages or your own domain.

This guide follows [rclone's own instructions](https://rclone.org/drive/#making-your-own-client-id),
which are updated when Google changes its console.
