# Connecting a real mailbox

A customer's invoices arrive by email. A mailbox channel (Channels in the customer platform) opens
the mailbox over IMAP with TLS on port 993, read-only, every two minutes, and takes in the PDF and
image attachments of mail that arrived after it was connected. Nothing is marked as read, moved or
deleted: the folder is opened with `EXAMINE` and messages are fetched with `BODY.PEEK`.

**What is proven:** the IMAP code is tested against a stand-in that answers as Gmail and Outlook are
documented to (`apps/api/tests/test_mailbox.py`). **What is not:** it has not been run against a
real Gmail or Outlook mailbox, because no mailbox credentials were available. `scripts/mailbox_check.py`
does that in two commands once they are.

## Gmail and Google Workspace

Google takes an **app password**: a 16-character password made for one application. It needs 2-Step
Verification on the account. Google Workspace stopped accepting the account's ordinary password
from third-party apps on 1 May 2025; app passwords are the exception that remains
(https://support.google.com/a/answer/14114704, https://support.google.com/mail/answer/185833).

1. Use a mailbox made for this, such as `invoices@yourbusiness.com`, not a personal one.
2. Turn on 2-Step Verification: https://myaccount.google.com/security
3. Create an app password: https://myaccount.google.com/apppasswords . Name it "Invoice intake".
4. Connect with server `imap.gmail.com`, the mailbox's address as the account, the app password,
   folder `INBOX`.

It will not work when: the account signs in with security keys only or has Advanced Protection (no
app passwords are offered); a Workspace administrator has restricted mail clients to OAuth ones; or
the account's password is changed later, which revokes every app password.

## Outlook.com and Microsoft 365

Microsoft takes **no password at all** for IMAP. Basic authentication ended for Outlook.com on
16 September 2024 and is disabled in every Microsoft 365 tenant, app passwords included
(https://support.microsoft.com/en-us/office/modern-authentication-methods-now-needed-to-continue-syncing-outlook-email-in-non-microsoft-email-apps-c5d65390-9676-4763-b41f-d7986499a90d,
https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online).
A mailbox there is read with a token from signing in to Microsoft (OAuth, the `XOAUTH2` IMAP
mechanism). The channel stores a refresh token in place of a password and trades it for a
short-lived access token at each check, keeping the newer refresh token whenever Microsoft issues
one.

That needs an application registered with Microsoft once. It costs nothing but only you can do it:

1. https://entra.microsoft.com > **App registrations > New registration**. Name it "Invoice
   intake". Supported accounts: personal and work accounts, unless you want one tenant only.
   No redirect address.
2. On the application: **Authentication > Allow public client flows: Yes**.
3. **API permissions > Add > APIs my organization uses > Office 365 Exchange Online > Delegated >
   `IMAP.AccessAsUser.All`**. For a work tenant an administrator may have to consent, and IMAP must
   be enabled for the mailbox.
4. Copy the **Application (client) ID**.
5. Sign in once: `MAILBOX_CLIENT_ID=<the id> uv run python scripts/outlook_signin.py` (from
   `apps/api`, as `uv run python ../../scripts/outlook_signin.py`). It shows a web address and a
   code; sign in as the mailbox's owner and agree. The token is written to `.outlook-token`.
6. Connect with server `outlook.office365.com`, the mailbox's address, **Signs in with: Microsoft
   sign-in**, the application id, and the token as the secret.

A refresh token unused for 90 days expires; a mailbox checked every two minutes never gets there.
If consent is withdrawn the channel says so and the mailbox is connected afresh.

There is no in-product "Sign in with Microsoft" button: the token is got with the script and pasted
in. That is the gap between this and something a customer could set up alone.

## Proving it against a real mailbox

With the app running (`bash demo/restaurant/start.sh`) and the credentials in the environment:

    export MAILBOX_HOST=imap.gmail.com MAILBOX_USER=invoices@yourbusiness.com
    read -s MAILBOX_PASSWORD && export MAILBOX_PASSWORD          # typed, not in shell history
    cd apps/api
    uv run python ../../scripts/mailbox_check.py connect         # proves the details; reads nothing
    #   ...send that mailbox one email with an invoice attached...
    uv run python ../../scripts/mailbox_check.py check           # takes it in, shows it processed
    uv run python ../../scripts/mailbox_check.py disconnect

For Microsoft set `MAILBOX_HOST=outlook.office365.com`, `MAILBOX_CLIENT_ID` and optionally
`MAILBOX_TENANT`, and no password. `check` reads every message's flags before and after and fails
if any changed. `newest` in place of `connect` and `check` uses the newest attachment already in
the mailbox, for when nothing new can be sent.

## What the stand-in had hidden

Found by reading the servers' documented behaviour, and fixed:

- **Outlook cannot be connected with a password.** There was no other way to sign in. Microsoft
  sign-in is now supported.
- **A refused sign-in said only "refused".** Gmail says when it wants an app password and Outlook
  when it blocks passwords; the person connecting is now told which.
- **Where the mailbox stands was asked with `STATUS` on the folder already open**, which a server
  need not answer. It is now read from the folder's opening, and asked only if that left it out.
- **A message fetched from a busy server can arrive with other updates beside it.** The first item
  was assumed to be the message.
- **Logos and signature images were taken in as documents.** A picture in the body of a message
  under 100 KB is now skipped; an attached file, or a photograph, is not.
- **None of the IMAP code had a test.** Only the seam above it did.
