# CIBugLog & JIRA Query Tool

A GUI application for querying and analyzing CI test results and JIRA issues.

## Overview

This tool provides an easy-to-use interface with two main tabs:

- **JIRA Query** - Search and filter JIRA issues with custom queries
- **CIBugLog** - Search, filter, and analyze CI test results from the CIBugLog system by test name, machine, run configuration, and date ranges

## Requirements

- Python 3.7+
- tkinter (usually included with Python)
- requests
- beautifulsoup4

## Installation

Install required dependencies:

```bash
pip install requests beautifulsoup4
```

## Configuration

### JIRA Token Setup

The application requires a JIRA API token for authentication. The token should be stored in a `jira_token` file in the project directory. To obtain a token:

1. Log in to your JIRA account
2. Go to Account Settings → Security → API tokens
3. Create a new API token
4. Copy the token and paste it into the `jira_token` file

The token is used to authenticate requests to the JIRA API for the JIRA Query tab functionality.

## Usage

Run the application:

```bash
python cibuglog_gui.py
```

## Files

- `cibuglog_gui.py` - Main GUI application
- `cibuglog_history.json` - Stores previous queries and filter history
- `jira_token` - Authentication token for JIRA integration

## Features

### JIRA Query Tab
- Query JIRA issues with custom JQL queries
- Filter and search JIRA issues
- View issue details and descriptions
- Sort results by any column

### CIBugLog Tab
- Query CI test results by test name, machine, and run configuration
- Filter results by date range
- View detailed test result information with color-coded status
- Export results to CSV
- View test logs in browser
