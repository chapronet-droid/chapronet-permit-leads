CHAPRONET LEAD INTELLIGENCE — LOCAL DASHBOARD ADD-ON V1

This add-on is designed for your existing:
  Downloads\ChaproNet_Daily_Lead_System_v2\chapronet_permit_leads

INSTALLATION
1. Extract this ZIP.
2. Copy these items into your existing chapronet_permit_leads folder:
     src\dashboard.py
     requirements_dashboard.txt
     install_dashboard.bat
     run_dashboard.bat
     README_DASHBOARD.txt
3. When Windows asks whether to merge the src folder, click Yes.
   This does not replace src\permit_leads.py.
4. Double-click install_dashboard.bat once.
5. Double-click run_daily.bat so current permit data exists.
6. Double-click run_dashboard.bat.
7. Your browser will open at:
     http://localhost:8501

WHAT V1 DOES
- Reads your real chapronet_permit_leads.csv report
- Shows KPI cards, lead queue, details, filters and map
- Lets you run the permit update from the dashboard
- Stores sales status, contact information, follow-up date and notes locally
- Creates state\dashboard.db automatically
- Keeps all data on your computer

CURRENT LIMITATION
Jobber and Confluence write actions are intentionally disabled in V1.
Your OAuth connection is proven, but secure token exchange and refresh-token
storage still need to be added before the dashboard can create CRM records.
