# Appendix A — SAP BTP Trial Setup: Step-by-Step

This appendix is for readers who are new to SAP Business Technology Platform. If you have worked with BTP before and already have a trial account with a running HANA Cloud instance, you can skip ahead to Chapter 3. If you are starting from scratch, follow every step here before opening Chapter 3. The main chapters assume this foundation is in place and do not repeat these instructions.

---

## What You Will Have at the End

By the time you reach the end of this appendix, you will have:

- An SAP BTP trial account registered and accessible at `cockpit.hanatrial.ondemand.com`
- A Cloud Foundry space named `dev` inside your trial subaccount
- A HANA Cloud instance named `msds-hana` (or your preferred name) in the Running state
- The vector engine confirmed available — the `REAL_VECTOR` column type is enabled by default in HANA Cloud from QRC2/2023 onwards
- Your HANA connection details (host, port, user, password) ready to paste into `agents/.env`
- The CF CLI installed and authenticated to your trial space

This is the minimum you need before executing any code in Chapter 3.

---

## Step 1 — Create a BTP Trial Account

### Navigate to the Trial Signup Page

Open a browser and go to `cockpit.hanatrial.ondemand.com`. You will see the SAP BTP homepage with a **Try for Free** button prominently displayed.

![SAP BTP homepage with Try for Free button](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/01-btp-homepage.png)
*Figure A.1 — The SAP BTP homepage. Click "Try for Free" to begin the trial registration process.*

If you already have an SAP Universal ID or an S-user ID from a corporate SAP system, you can log in directly without registering. If not, click **Try for Free** and proceed to registration.

### Register Your Account

On the registration page, fill in your first name, last name, email address, and choose a password. Use a personal email address if possible. Some corporate email domains block activation emails or have policies that prevent trial account creation.

![BTP trial registration form](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/01-btp-trial-signup.png)
*Figure A.2 — The trial registration form. Enter your details and accept the terms of service.*

After submitting, SAP will send a verification email to the address you provided. Check your inbox (and spam folder) and click the activation link. The link expires after 24 hours.

![BTP trial login page after verification](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/01-btp-trial-login.png)
*Figure A.3 — Once your email is verified, return to the login page and sign in with your new credentials.*

### Complete Registration and Choose a Region

After logging in for the first time, BTP will ask you to complete your registration profile. Fill in your details.

![BTP registration completion screen](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/02-btp-register.png)
*Figure A.4 — Complete your profile to finalize the trial account.*

You will then be presented with a region selection screen. BTP trial accounts support several regions. **Choose US East (US10, Virginia)** if you are following this book closely. The Vertex AI API we use is hosted on Google Cloud in the US, and keeping your BTP account in the same broad geography minimizes network latency between your HANA Cloud instance and external API calls.

![BTP region selection screen](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/03-btp-region.png)
*Figure A.5 — Region selection. US East (US10) is recommended for readers following this book.*

> **Note:** The region you choose here is permanent for your trial account. Your Cloud Foundry space and HANA Cloud instance will be created in this same region automatically. Do not attempt to change the region after this point — it is not possible without creating a new account.

Click **Proceed**. BTP will spend 30–60 seconds provisioning your trial account.

### Confirm the Trial Account Is Ready

When provisioning completes, you will land on the BTP Cockpit home screen. You should see a **trial** tile under your Global Account name.

![BTP trial created confirmation screen](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/04-btp-trial-created.png)
*Figure A.6 — Your BTP trial account is ready. You should see the "trial" subaccount tile on the home screen.*

If you see an error or the page appears empty, wait 2 minutes and refresh. Trial provisioning occasionally takes longer than expected.

---

## Step 2 — Navigate the BTP Cockpit

Before diving into service setup, take one minute to understand the cockpit's structure. This prevents confusion later.

**Global Account** is the top-level container for your BTP subscription. It holds entitlements (the services you are allowed to use) and organizes everything underneath.

**Subaccount** is a logical partition inside your Global Account. Your trial comes with one subaccount called "trial." This is where you will create services, deploy applications, and manage credentials.

**Cloud Foundry Space** is a runtime environment inside a subaccount. The space called `dev` is where your application code runs.

### Finding Your Trial Subaccount

From the BTP Cockpit home screen, click the **trial** tile. This opens your trial subaccount overview.

![BTP trial subaccount overview](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/05-btp-subaccount.png)
*Figure A.7 — The trial subaccount overview page. Note the API Endpoint value in the Cloud Foundry section — you will need this in Step 8.*

On this page you will see several sections:

- **Cloud Foundry Environment** — shows your CF organization name and API endpoint
- **Instances and Subscriptions** — shows services you have created
- **Security** — role collections and trust configuration

Look at the Cloud Foundry Environment section and write down the **API Endpoint**. It will look like `https://api.cf.us10.hana.ondemand.com` (the region code in the middle will match your choice from Step 1).

### Finding the CF Space

In the left navigation panel, click **Cloud Foundry** and then **Spaces**. You will see a space named `dev`. This is your deployment target for all the application code in this book.

[SCREENSHOT: Left navigation showing Cloud Foundry > Spaces with the dev space listed]

If the `dev` space is not visible, proceed to Step 3 to create it.

---

## Step 3 — Enable Cloud Foundry

BTP trial accounts come with the Cloud Foundry runtime pre-enabled in most regions, but it is worth verifying.

### Check CF Runtime Status

From your trial subaccount overview, look at the **Cloud Foundry Environment** section. If it shows an org name and API endpoint, CF is already enabled. Skip to "Create the dev Space" below.

If you see a button labeled **Enable Cloud Foundry**, click it. You will be prompted to choose an instance plan — select **trial**. Enabling CF takes about 2 minutes.

[SCREENSHOT: Cloud Foundry Environment section showing "Enable Cloud Foundry" button, or alternatively showing the org name and API endpoint if already enabled]

### Create the dev Space

Once CF is enabled and you have an org, click **Create Space**. Name it `dev`. Leave the default role assignments in place. Click **Create**.

[SCREENSHOT: Create Space dialog with "dev" entered as the space name]

You now have a CF space ready to receive deployments.

### Note the CF API Endpoint

Write down the following three values from the Cloud Foundry Environment section of your subaccount. You will use all three in Step 8 when you run `cf login`.

| Item | Where to Find It | Example |
|------|-----------------|---------|
| API Endpoint | CF Environment section, subaccount overview | `https://api.cf.us10.hana.ondemand.com` |
| Org Name | CF Environment section, under API Endpoint | `trial-us10-<your-id>` |
| Space Name | Cloud Foundry → Spaces | `dev` |

---

## Step 4 — Add HANA Cloud Entitlement

Before you can create a HANA Cloud instance, your Global Account must have the HANA Cloud entitlement assigned to your trial subaccount. In a trial account this is usually pre-configured, but verify it now to avoid a cryptic error during provisioning.

### Navigate to Entitlements

Click the breadcrumb at the top of the cockpit to go back to your **Global Account** view. In the left navigation, click **Entitlements** → **Entity Assignments**.

![HANA Cloud entitlements page](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/02-hana-entitlements.png)
*Figure A.8 — The Entity Assignments screen under Entitlements. This is where service plans are allocated to subaccounts.*

In the **Select Entities** dropdown, choose your **trial** subaccount. Click **Go**. You will see a list of services currently assigned to the subaccount.

Look for a row with **SAP HANA Cloud** in the service column and **hana** in the plan column. If it is already there with a quota of at least 1, you are set — skip to Step 5.

If HANA Cloud is not in the list, click **Configure Entitlements** → **Add Service Plans**. In the dialog, search for "HANA Cloud", expand the result, check the `hana` plan, and click **Add 1 Service Plan**. Then click **Save**.

![Global account view showing HANA Cloud entitlement](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/05-btp-global-account.png)
*Figure A.9 — Global Account view. Navigate to Entitlements > Entity Assignments to manage service plan allocations.*

---

## Step 5 — Provision HANA Cloud

With the entitlement in place, you can now create the database instance.

### Open the Service Marketplace

Navigate back to your **trial subaccount**. In the left navigation, click **Services** → **Service Marketplace**. The marketplace shows all services available to your subaccount. In the search bar, type "HANA Cloud."

![BTP Service Marketplace](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/btp/06-btp-marketplace.png)
*Figure A.10 — The BTP Service Marketplace. Search for "HANA Cloud" to find the tile.*

Click the **SAP HANA Cloud** tile. On the service detail page, click **Create** in the upper right corner.

### Fill in the Provisioning Form

![HANA Cloud create instance form](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/03-hana-create.png)
*Figure A.11 — The HANA Cloud instance creation wizard. Fill in the instance name and administrator password.*

Fill in the following fields:

| Field | Recommended Value | Notes |
|-------|------------------|-------|
| Instance Name | `msds-hana` | Any name works; the code in this book uses `msds-hana` as a reference |
| Administrator Password | Your choice | Must be at least 8 characters with uppercase, lowercase, and a digit |
| Memory | 30 GB | Trial default — do not reduce; the vector engine requires this headroom |
| Storage | 120 GB | Trial default — leave as is |

> **Critical:** Write down the administrator password the moment you set it. You cannot retrieve it later. It will go into your `agents/.env` file as `HANA_PASSWORD`. If you lose it, you must delete the instance and reprovision.

Click **Create**. A confirmation dialog will appear. Click **Create** again to confirm.

### Wait for Provisioning

BTP will redirect you to the **SAP HANA Cloud Central** tool, which shows all your HANA Cloud instances.

![HANA Cloud Central instance view](/Users/I310202/01.Local_Developments/99-Books/book/book-agentic-hybrid-rag-on-btp/docs/screenshots/hana/04-hana-central.png)
*Figure A.12 — SAP HANA Cloud Central showing your new instance. The status will read "Starting" for 10–15 minutes.*

The status will show **Starting** for approximately 10–15 minutes. This is normal. Do not close the browser tab. When the status changes to **Running**, the instance is ready.

If you see **Failed** status, the most common cause is that the entitlement was not properly assigned. Go back to Step 4, verify the `hana` plan is assigned with quota ≥ 1, and try creating the instance again.

---

## Step 6 — Enable the Vector Engine

The `REAL_VECTOR` column type — which enables vector similarity search in HANA Cloud — is part of the HANA Cloud core engine. It is available by default in all HANA Cloud instances created from QRC2/2023 onwards, which includes all current trial instances. No separate toggle or purchase is required.

There are, however, two optional features that the code in Chapter 6 (document ingestion) benefits from: **Script Server** and **Document Store**. Enable these now to avoid re-editing the instance later.

### Open HANA Cloud Central

If you are not already in HANA Cloud Central, navigate to it from your trial subaccount: click **Services** → **Instances and Subscriptions**, find your HANA Cloud instance in the list, click the three-dot menu on the right side of its row, and select **Open in SAP HANA Cloud Central**.

Alternatively, if you are already in HANA Cloud Central, click on your instance name to open the instance detail view.

### Edit the Instance Configuration

In HANA Cloud Central, click the three-dot menu (labeled **Actions**) next to your instance name. Select **Edit**.

The instance edit form opens. Scroll down until you see the **Additional Features** section. You will find checkboxes for:

- **Script Server** — enables server-side scripting and is required for certain built-in procedures
- **Document Store** — adds JSON document storage and is used by some ingestion patterns in Chapter 6

Check both boxes if they are not already checked. The vector engine (`REAL_VECTOR`) is listed as a core capability in this section — confirm it shows as enabled.

Click **Save**. HANA Cloud will apply the configuration change, which takes 2–3 minutes. The instance status will briefly show **Updating** and return to **Running**.

> **Note on the vector engine:** If you are reading the HANA Cloud documentation and see references to "Script Server" being required for vector search in older documentation, that applied to versions prior to QRC2/2023. Current HANA Cloud trial instances support `REAL_VECTOR` natively without Script Server. Script Server is still worth enabling for the scripting features used in Chapter 6.

---

## Step 7 — Get the HANA Connection Details

You now need four pieces of information from your HANA Cloud instance. These go into the `agents/.env` file in Chapter 3.

### Copy the SQL Endpoint

In SAP HANA Cloud Central, click the three-dot **Actions** menu next to your instance. Select **Copy SQL Endpoint**. This copies a string to your clipboard in the following format:

```
<instance-id>.hana.trial-us10.hanacloud.ondemand.com:443
```

The structure of your four connection parameters is:

| Parameter | How to Derive It | Example |
|-----------|-----------------|---------|
| `HANA_HOST` | Everything in the SQL endpoint before the colon | `abc123def456.hana.trial-us10.hanacloud.ondemand.com` |
| `HANA_PORT` | The number after the colon | `443` |
| `HANA_USER` | Fixed value for trial instances | `DBADMIN` |
| `HANA_PASSWORD` | The password you set during provisioning in Step 5 | (your chosen password) |

Open `agents/.env` (or create it if it does not exist yet) and add these four lines:

```ini
HANA_HOST=<your-instance-id>.hana.trial-us10.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=<your-password>
```

Replace the placeholder values with the values specific to your instance. Do not add quotes around the values.

> **Security reminder:** The `.env` file is listed in `.gitignore` in the project repository. Never commit this file to source control. If you are working in a shared environment, restrict read access to this file at the OS level.

---

## Step 8 — Install the CF CLI

The CF CLI (Cloud Foundry Command Line Interface) is how you deploy applications to your BTP Cloud Foundry space from your local machine. You need it in Chapter 11 when you deploy the agents to production.

### Install on macOS

If you have Homebrew installed, run:

```bash
brew install cloudfoundry/tap/cf-cli@8
```

If you do not have Homebrew, download the installer from [https://github.com/cloudfoundry/cli/releases](https://github.com/cloudfoundry/cli/releases) — choose the latest v8 release and the macOS binary.

### Install on Windows

Download the Windows installer from `cloudfoundry.org/cf-cli`. Run the `.exe` installer and follow the prompts. The CF CLI will be added to your PATH automatically.

### Verify the Installation

Open a terminal (or PowerShell on Windows) and run:

```bash
cf --version
```

You should see output similar to:

```
cf version 8.x.x+...
```

### Authenticate to Your BTP Space

Use the Single Sign-On method to authenticate. This avoids storing your SAP password in the terminal and works reliably with multi-factor authentication.

```bash
cf login -a https://api.cf.us10.hana.ondemand.com --sso
```

Replace `us10` with your actual region code if different. The CLI will print a temporary passcode URL. Open that URL in your browser, copy the passcode it displays, and paste it back into the terminal.

After authentication, the CLI will show you a list of orgs and spaces. Select your trial org and then the `dev` space.

To verify you are in the right place, run:

```bash
cf target
```

The output should show your API endpoint, org name, and the `dev` space.

---

## Verification Checklist

Before moving to Chapter 3, confirm each of the following items. Do not skip this — a missing item here causes non-obvious errors two or three chapters later.

- [ ] **BTP Cockpit login works.** You can open `cockpit.hanatrial.ondemand.com` and reach your Global Account home screen without being asked to register again.

- [ ] **Trial subaccount exists.** Clicking the **trial** tile takes you to a subaccount overview that shows a Cloud Foundry Environment section with an API Endpoint URL.

- [ ] **CF space named `dev` exists.** Under Cloud Foundry → Spaces in the left navigation, you can see the `dev` space.

- [ ] **HANA Cloud instance is Running.** In SAP HANA Cloud Central (reachable via Services → Instances and Subscriptions → Actions menu → Open in SAP HANA Cloud Central), your instance shows green **Running** status.

- [ ] **HANA connection details are saved.** Your `agents/.env` file contains `HANA_HOST`, `HANA_PORT`, `HANA_USER`, and `HANA_PASSWORD` with real values. The host ends in `.hanacloud.ondemand.com`.

- [ ] **CF CLI is authenticated.** Running `cf target` in your terminal shows the correct API endpoint, org, and `dev` space — no authentication error.

All six checked? You are ready for Chapter 3.

---

## Common Problems and Fixes

**"I never received the verification email."**
Check your spam folder. If the email is not there after 5 minutes, return to the trial signup page and request a new verification email. Gmail and Outlook accounts generally receive SAP trial emails without issue. Some corporate email servers block messages from `@sap.com` senders.

**"My HANA Cloud instance status is stuck on Starting for more than 20 minutes."**
This occasionally happens in trial environments under load. Refresh the HANA Cloud Central page. If the status has not changed after 30 minutes, click the three-dot Actions menu on the instance and select **Restart**. If the instance shows **Failed**, delete it and re-create it from Step 5.

**"I cannot find the `hana` service plan in the marketplace."**
The entitlement is not assigned. Go to your Global Account → Entitlements → Entity Assignments, select your trial subaccount, and confirm the SAP HANA Cloud `hana` plan is present with a quota of 1. If not, follow Step 4 to add it.

**"`cf login` fails with 'Invalid credentials'."**
Use the `--sso` flag as shown in Step 8. Plain username/password login often fails if your SAP account requires multi-factor authentication or if the password contains special characters that the terminal interprets differently. The SSO passcode method avoids both issues.

**"I set a HANA password but I am not sure I wrote it down correctly."**
There is no password recovery for HANA Cloud trial instances. If you are unsure, the safest approach is to delete the instance and reprovision with a new password you can record with confidence. Deletion takes seconds; reprovisioning takes 10–15 minutes.
