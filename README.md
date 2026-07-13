# ChaproNet Daily Permit Lead System

This Windows package automatically pulls newly issued Chicago building permits, targets the South and Southwest Sides, scores opportunities for CCTV/access control/intercom/networking/A-V work, tracks duplicates, and creates an outreach workbook.

## One-time setup

1. Extract the ZIP completely.
2. Open the extracted `chapronet_permit_leads` folder.
3. Double-click `install_windows.bat`.
4. Double-click `run_daily.bat` once to test it.
5. Right-click `SETUP_DAILY_AUTOMATION.bat` and select **Run as administrator**.

The scheduled job runs daily at 7:00 AM. Windows will run it later when the computer becomes available if it was asleep at 7:00 AM.

## Daily files

Inside `output`:

- `chapronet_permit_leads.xlsx`: All Leads, New Since Last Run, Top Leads, Outreach Queue and Run Summary.
- `chapronet_permit_leads.csv`: complete current lead list.
- `chapronet_top_leads.csv`: highest-scoring opportunities.
- `jobber_ready_leads.csv`: new permits arranged for client/lead import and review.

The workbook includes one-click links for Google Maps, property-owner research, GC/company research, the Cook County Assessor search, and the City permit source. It also includes editable phone, email, company, status, follow-up and notes columns.

## Optional daily email

Open `.env` with Notepad and complete the Gmail settings. Use a Google app password, not your normal password.

```text
EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=youraddress@gmail.com
SMTP_PASSWORD=your-16-character-app-password
EMAIL_FROM=youraddress@gmail.com
EMAIL_TO=youraddress@gmail.com
EMAIL_ONLY_WHEN_NEW=true
```

## Important limitation

Chicago's public permit feed usually provides names but not dependable phone numbers or email addresses. This package does not invent contact information. It creates direct research links and a structured outreach queue. Fully automatic verified phone/email enrichment requires a separate licensed data provider/API and its API key.
