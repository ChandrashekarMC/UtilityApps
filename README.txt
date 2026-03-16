# Fresh Requirements
## Personal Tasks/Todo

### At side bar, Menu should have
1. Create Task (Radio button, selected by default)
2. Tasks List (Radio button)
3. Categories  (Radio button)
4. Calendar View (Radio button)

## Create/Edit Task Page:
When Create Task is selected "Create/Edit Task Form" is displayed in the main area.
### Task attributes are
* Name
* Task Id(X.Y.Z format) where X is Main Task id, Y is the Sub task Id and Z is * the Unit task id.
* Category
* Due Date(DD-MM-YYYY format)
* Priority(Low, Medium, High)
* Urgency(Low, Medium, High)
* Progress(0% to 100% with steps of 5%)
### Recurring Task:  Yes/No
    If Yes:
	1. Frequency: 
		*  Hourly : For every X hours, Y minutes
		*  Daily  : For every X days
		*  Weekly : For every X weeks, On certain weekdays selected between Sunday to Saturday
		*  Monthly: For every X months, On a date
		*  Yearly : For every X years, 
	2. Recurring End options:
		*  Ends on a specific date
		*  Ends on X number of occurrences
		*  Recurring for ever
### Reminder Needed:  Yes/No
    If Yes, allow following configurations:
	1. Number of days, hours, minutes before due date
	2. Type/Sound of alarm
	3. Snooze option
	4. Set Volume
	5. Allow upto 3 reminders for the same task 
Note 1: There should be a Notes related tasks can be recorded.
Note 2: There should be a way to attach a document to a task.
Finally this page should have a button to save the created or edited task.

## Task List Page:
[ ** Below configuration displayed in sidebar ** ]
Tasks can be filtered, sorted, hierarchical tasks
In stream lit side bar, there should be option to filter all the tasks for
    1. Category
    2. Priority
    3. Urgency
    4. Starred
    5. Due date
After filtering, there are sorting options
    1. Sort by Creation Date
    2. Sort by Due date
    3. Sort by Completed Date
    4. Sort by Archived Date
After sorting, provide a check box to display the hierarchical tasks
    1. Main task
    2. Sub tasks
    3. Unit tasks
[ ** Below configuration displayed in Main area ** ]
Generally, all tasks are displayed normally, but when hierarchical check box is enabled
* Main tasks will display Task id as X.0.0
* All the sub tasks belonging to this main task will have Task id X.Y.0
* All the unit tasks belonging to this sub task will have Task id X.Y.Z
## This page has three Tabs
### Tab 1: Active tasks : 
    These tasks have three columns that can be edited.
    * Task Complete Checkbox : When checked, move the task from active table to completed table.
    * Task Archive Checkbox : When checked, move the task from active table to Archived table.
    * Edit Task Checkbox : Any one task can be checked, Create/Edit page opens and task can be modified	
### Tab 2: Completed tasks : 
    Completed tasks. It has additional column when checked moves the task back to active
### Tab 3: Archived tasks : 
    Archived tasks. It has additional column when checked moves the task back to active

Categories Page:
Following are the default categories that can not be created or deleted.
1. Personal
2. Official
3. Wishlist
4. Birthday
5. All
Should have an option to create additional categories. These created categories can also be deleted.

Calendar View Page:
Calendar for the month should be displayed.
For a selected date, all the active tasks should be displayed.
Active tasks are those that are not completed and not archived.

Dashboard Page:

Deployment: 
# On Build Server:
cmd> python .\bundle_release.py --profile flask --output .\artifacts\persmgr_release3Mar11pm.zip --quiet
cmd> scp .\artifacts\persmgr_release3Mar11pm.zip mcc@178.16.137.146:/home/mcc
# On Hosting server:
/home/mcc> cd ~/apps/PersMgr
PersMgr>    unzip -o ~/persmgr_release3Mar11pm.zip -d .
# Fill the missing information in following files under deploy WorkingDirectory
# Replace <HOSTINGER_USER> with mcc in files start_flask.sh, persmgr-flask.service
# Replace <HOSTINGER_USER> with chikku.tech in file nginx-persmgr-flask.conf
PersMgr> 

Google Login Setup (OAuth)
1. In Google Cloud Console, create an OAuth 2.0 Client ID (Web application).
2. Add Authorized redirect URI:
    - Local dev: http://localhost:8000/auth/google/callback
    - Server: https://<your-domain>/auth/google/callback
3. Set environment variables before starting Flask/Gunicorn:
    - GOOGLE_CLIENT_ID=<google-client-id>
    - GOOGLE_CLIENT_SECRET=<google-client-secret>
    - FLASK_SECRET_KEY=<strong-random-secret>
    - Optional: PERSONAL_GOOGLE_ALLOWED_EMAILS=<email1,email2>
    - Recommended on VPS: set these in deploy/persmgr-flask.env
4. Install dependencies again after update:
    - pip install -r requirements.txt

Notes:
- Gmail username/password is not collected by this app.
- Authentication is handled securely by Google Sign-In (OAuth).