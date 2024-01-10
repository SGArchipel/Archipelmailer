# Archipelmailer
Create google groups based on json data, in this case from WISA

- Make sure you have the correct credentials for the google api and the WISA api.
- When creating the project in google cloud console make sure to activate the correct scopes (see the example of .env).
- Create your own .env file, an example is added in to this repo.

## Before you can run the script
1. Go to https://console.cloud.google.com/ 
2. Create new Project
3. Give it a name and location
4. Select the created project
5. Go to APIs and services
6. Click on "+ enable apis and services"
7. Search for "Admin SDK API" and enable this api
8. Search for "Group Settings API" and enable this api
9. Go to Credentials on the left side of the screen
10. Click on "create credentials" -> OAuth client ID
11. Configure consent screen
12. User type: internal, fill in the necessary boxes
13. Add scopes, paste the following line in the box "manually add scopes":
https://www.googleapis.com/auth/apps.groups.settings,https://www.googleapis.com/auth/admin.directory.user,https://www.googleapis.com/auth/admin.directory.group.readonly,https://www.googleapis.com/auth/admin.directory.group.member.readonly,https://www.googleapis.com/auth/admin.directory.group.member,https://www.googleapis.com/auth/admin.directory.group
14. Save and continue x2
15. Go back to Credentials
16. Click on "create credentials" -> OAuth client ID
17. Application type: desktop app
18. Download json and paste this line in the .env file where the credentials line has to go
19. Make sure that your .env file is created and filled in correctly, otherwise the program is not going to work.

## Very important to check
In the function get_google_groups you have to change the domain name of the groups you do not want to compare to the directory json file, otherwise the script is going to remove all the members from the groups it cannot find in the directory json file.

Have fun!
