[(en-US)](./readme-en.md) | [(ko-KR)](./readme.md)

# ISHS WIKI

<img src="https://github.com/gyu0ne/ISHS_Wiki/blob/main/views/main_css/file/ishs-logo.png" width="200" height="200"/>

This is an improved openNAMU-based wiki engine built for the ISHS WIKI, used at Incheon Science High School's [ISHS WIKI](ishswiki.xyz). Built on openNAMU 3.6.0.

# Usage
## Logging In
* Authenticating with your RiroSchool account automatically handles registration/login.
* Without logging in you can only read documents; attempting to edit one redirects you to the login page.
## Reading / Searching Documents
* The search bar at the top searches both document titles and content together.
* The sidebar shows recent changes and trending (popular) documents.
## Editing Documents
* Once logged in, use the edit button at the top of a document to write or modify it using Namumark syntax.
* Footnotes, math rendering, and related-document links are supported.
## Other
* You can toggle dark mode from the settings menu.
* Logged-in users can view their own browsing history.

## Running It Yourself
```
pip3 install --upgrade -r requirements.txt
python3 app.py
```
* Windows: run `run_windows.bat`
* Linux: run `run_ubuntu.sh`
### Run with Docker
```
docker build . -t ishs-wiki
docker run -p 3000:3000 -v data:/app/data --name ishs-wiki ishs-wiki
```

# Changes
## 0.0.1 - 2025.08.29 (Alpha)
* Basic settings modified
## 0.0.2 - 2025.08.31
* Introduced RiroSchool authentication system
## 0.1.0
* Fixed an error occurring during login authentication
* Added ID-related guidance text to the registration page
## 0.1.1
* Hid the watchlist menu item
* Changed the position of the last-edit time display
## 0.1.2
* Fixed student ID error
* Changed document modification time location
## 0.1.3
* Fixed menu/header layout on mobile screens
## 0.1.4 - 2025.09.01
* Added OpenGraph information
* Blocked external users from documents related to people
## 0.1.5
* Modified the document format created on registration
## 0.1.6
* Added authentication for existing accounts
## 0.1.7 - 2025.09.02
* Redirected document edit attempts by non-logged-in users to the login page
## 0.2.0
* Added meal/schedule features
* Changed the ban criteria (ID --> real name)
## 0.2.1
* Fixed grammar errors in the initial user document
* Added search auto-complete
## 0.2.2
* Fixed a bug in the schedule feature
## 0.3.0 - 2025.09.04
* Fixed a security vulnerability
* Displayed student ID/name on the profile page
## 0.3.1
* Fixed a Namumark rendering bug
## 0.3.2
* Added teacher login
## 0.3.3 - 2025.09.05
* Fixed a student ID handling error during registration
## 0.3.4
* Fixed an error handling different account formats (student ID/email) on RiroSchool login
## 0.3.5
* Fixed a timetable bug
* Minor dark mode CSS fixes
* Fixed the teacher registration system
## 0.3.6
* Added an automatic login feature
* Cleaned up unnecessary code
## 0.3.7 - 2025.09.07
* Blocked access to person-related documents for non-logged-in accounts
## 0.3.8
* Fixed a preview rendering error
* Changed the RiroSchool authentication method
## 0.3.9
* Added a feature to add alumni accounts
## 1.0.0 - 2025.10.19 (Beta)
* Major design overhaul
* Added a recent changes panel to the right side of the screen
* Redirect back to the previous screen after login
* Show document title/content matches together in search
* Added RiroSchool/school-life links to the school-life section
* Numerous minor bug fixes (line breaks, dividers, etc.)
* Hover preview for linked documents
* Hover preview for footnotes (not fully complete)
* Removed unnecessary features
* Added a star/favorite feature
* Added a logo
## 1.0.1 - 2025.10.21
* Improved mobile-specific design
## 1.0.2 - 2025.10.23
* Improved search result display, removed the right-side panel on portrait screens
* Increased font size in preview mode
* Added an "other tools" menu, fixed an ACL settings bug
* Minor logo/design fixes
## 1.0.3 - 2025.11.20
* Integrated Google Analytics tag
* Added Google AdSense meta tag
## 1.1.0 - 2026.01.12
* Added a search auto-correction feature
* Improved search functionality
* Fixed a light mode bug
* Adjusted ad placement and skin design
## 1.2.0 - 2026.01.30
* Overhauled the RiroSchool authentication system, updated registration flows and Terms of Service
* Added a footnote feature and fixed related bugs
* Added math rendering support
* Added a personal view history feature
* Overhauled dark mode (link colors, etc.)
* Improved mobile UI
* Fixed bugs in account settings and document history display
* Improved SEO and added automatic sitemap generation
## 1.2.1 - 2026.02.28
* Blocked exposure of email addresses
* Added a feature to move multiple documents at once
* Re-verify login status when editing a document
## 1.2.2 - 2026.03.15
* Improved the RiroSchool re-authentication flow
* Adjusted ID rules
* Improved nickname duplicate checking
* Fixed ban logic, added admin self-unban feature
* Cleaned up the admin checkmark icon on user links
* Hid personal information for non-logged-in (IP) users
* Added login guidance text
## 1.2.3 - 2026.03.23
* Fixed auto-login logic, fixed bot verification logic
* Added a trending documents sidebar
## 1.3.0 - 2026.03.30 (Performance)
* Improved response speed through DB optimization
* Improved trending search aggregation (shorter window, added caching)
* Added session-based spam protection for view logging
* Improved search UI and mobile search
* Added identity-based auto-ban on registration
* Fixed dark mode hover colors
## 1.3.1 - 2026.04.08
* Added background auto-refresh for the recent changes sidebar
## 1.3.2 - 2026.04.13
* Improved RiroSchool login/re-authentication related features
## 1.3.3 - 2026.05.18
* Fixed a nickname revert bug
* Improved handling when moving to deleted documents, prevented self-move
## 1.3.4 - 2026.05.30
* Ban expiration is now automatically reflected at check time
## 1.3.5 - 2026.06.16
* Minimized ad exposure on person/private documents to address AdSense review
## 1.4.0 - 2026.08.14
* Refactored RiroSchool authentication parsing logic
* Restored the graph view feature
* Added sidebar toggles (hide mode), reworked the discussions sidebar UI
* Fixed AdSense layout
* Changed the default category syntax on file upload
* Fixed a related-documents display syntax error
