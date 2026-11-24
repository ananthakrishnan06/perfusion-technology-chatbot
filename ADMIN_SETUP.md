# Perfusion AI administration

The dashboard uses your existing PostgreSQL database and application session cookies. Start the new backend with an account that can create tables. Startup creates the administration tables alongside the existing schema. Existing accounts and the bundled FAISS index remain available.

1. Set `ADMIN_BOOTSTRAP_EMAIL` to the requested fictional administrator email in your hosting provider's secret settings. Choose an address that has never been registered.
2. Generate the initial Argon2 hash locally from the project root. Enter the initial password at the prompt. Save the printed hash as the value of `ADMIN_BOOTSTRAP_PASSWORD_HASH`. Keep the bootstrap configuration and any credentials out of source control.

   ```sh
   python -c "from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass('Initial administrator password: ')))"
   ```

3. Start the backend and sign in from the website with the bootstrap email and initial password. The dashboard opens directly and requires a password change. Sign in again with your new password. Clear `ADMIN_BOOTSTRAP_PASSWORD_HASH` from the hosting environment after rotation. Keep `ADMIN_BOOTSTRAP_EMAIL` configured so the existing administrator can sign in.
4. To open the dashboard directly, go to `/admin` on Vercel or `/api/v1/admin/page` on the backend. The backend checks the session before it serves the dashboard.

Use the dashboard to upload and categorize PDFs. The database stores originals and chunks from new uploads. At startup, the backend restores them to its local FAISS and BM25 indexes. Run one backend replica that writes to this knowledge base. Bundled legacy PDFs whose original files are absent still have searchable text but cannot be previewed. To enable OCR, install Tesseract and its language data in the backend environment and set `PDF_OCR_LANG=eng`. Failed items can be reprocessed after OCR is configured.

Usage reports begin when this version starts recording requests. They count admitted AI API requests, record elapsed time and outcomes, and attribute PDF use from returned citations. The current answer interface does not collect provider token counts or token-based costs. The response token limit controls generation size. The server's `MAX_UPLOAD_SIZE_MB` is the hard upload ceiling. Configure a smaller working limit in the dashboard if needed.

Suspensions and revocations are enforced by this application. Removing a user deletes their application account, conversations, and memories and blocks the same external identity from entering again. It does not delete that identity from Google or Supabase. Analytics and audit history retain opaque IDs to support reporting.
