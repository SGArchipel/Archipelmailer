from dotenv import load_dotenv
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json
import os
import requests
from datetime import date
from googleapiclient.errors import HttpError
from typing import List
import logging
from googleapiclient.errors import HttpError
import time
from datetime import timedelta, datetime
import logging
import smtplib
from email.mime.text import MIMEText

logging.basicConfig(filename="ArchipelMailer.log", level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Load .env file
load_dotenv()

# Load credentials and scopes google
CREDENTIALS = json.loads(os.getenv("CREDENTIALS"))
SCOPES = json.loads(os.getenv("SCOPES"))

def authenticate():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds is None or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

# Create service-object for Google Directory API
def create_directory_service():
    return build('admin', 'directory_v1', credentials=authenticate())

# Load other values out of .env file
INSTELLINGSNUMMERS = os.getenv("INSTELLINGSNUMMERS")
# Get date of today
today = date.today()

if today.month==7:
    today=today.replace(day=28,month=6) # If today is in july, change the date to 28/6/year
elif today.month==8:
    today=today.replace(day=2,month=9) # If today is in august, change the date to 2/9/year

# Format date so that it works for WISA
formatted_date = today.strftime("%d/%m/%Y")
WISA_URL=os.getenv("WISA_URL")
base_url = f"{WISA_URL}/QUERY/OUDERMLR?werkdatum={formatted_date}&instellingsnummer={INSTELLINGSNUMMERS}"
username_env = os.getenv("USERNAME_ENV")
password_env = os.getenv("PASSWORD_ENV")
domain_name = os.getenv("DOMAIN")

def load_json_data():
    # Make request to WISA in JSON format
    url = f"{base_url}&_username_={username_env}&_password_={password_env}&format=json"
    response = requests.get(url)
    if response.status_code == 200:
        json_data = json.loads(response.text)

        # Write JSON to file (not necessary)
        with open("output/data.json", "w") as data_file:
            json.dump(json_data, data_file, indent=2)

        return json_data
    else:
        print(f"Error loading json data: {response.status_code}")
        logging.info(f"Error loading json data: {response.status_code}")
        return None

# Function to generate address of group based on code from WISA
def generate_google_group_address(class_code):
    # class_code comes in as LS-L2C for example, needs to get out as l2c@hhhls.sgarchipel.be
    if "-" in class_code:
        # Split in 2: 1 part represents the school, 1 part represents the code of the class
        parts = class_code.split("-")
        class_code_suffix = parts[-1].lower().replace(" ", "")
        first_part = parts[0].lower()
        
        # Mapping of first parts of class code
        # in this example: when 'LS' -> transform to hhhls for the group address
        klascode_mappings = {"v": "vl", "oh": "wz", "ls": "hhhls", "ks": "hhhks", "oudhe": "wz", "bl": "bolo", "z": "zb", "j": "sk", "m": "moza", "a" : "vl"}
        first_part = klascode_mappings.get(first_part, first_part)
        
        # in this example returns: l2c@hhhls.sgarchipel.be
        return f"{class_code_suffix}@{first_part}.{domain_name}"
    else:
        return f"unknown_klascode_{class_code_suffix}@{domain_name}"

def add_member_to_group(service, group_email, member_email, wrong_mails, added_addresses):
    try:
        # Add member to a google group
        service.members().insert(groupKey=group_email, body={"email": member_email, "role": "MEMBER"}).execute()
        print(f"E-mailadres {member_email} added to group: {group_email}")
        logging.info(f"E-mailadres {member_email} added to group: {group_email}")
        #added_addresses.add(f"E-mailadres {member_email} added to group: {group_email}")
        if group_email not in added_addresses:
            added_addresses[group_email]=set()
        
        added_addresses[group_email].add(member_email)
        
    except Exception as e:
        if hasattr(e, 'resp') and e.resp.status == 409 and 'duplicate' in str(e):
            logging.info(f"Error when trying to add {member_email} to the group {group_email}: duplicate")
            print(f"Error when trying to add {member_email} to the group {group_email}: duplicate")
        elif hasattr(e, 'resp') and e.resp.status == 404:
            # Google gives this error code when a google account does not exist.
            # store all the faulty mail addresses for an overview at the end of the script
            if group_email not in wrong_mails:
                wrong_mails[group_email]=set()
            wrong_mails[group_email].add(member_email)
        else:
            print(f"Error when trying to add {member_email} to the group {group_email}: {e}")
            logging.error(f"Error when trying to add {member_email} to the group {group_email}: {e}")


def create_google_group_if_not_exists(service, email, name, description):
    try:
        # Try to get the group from the api, if it gives an error, the function can create one
        existing_group = service.groups().get(groupKey=email).execute()
        print(f"Group {email} already exists.")
        logging.info(f"Group {email} already exists.")
        return existing_group
    except HttpError as e:
        # If the group is not found, create a new one
        if e.resp.status == 404:
            try:
                created_group = service.groups().insert(body={
                    "email": email,
                    "name": name,
                    "description": description
                }).execute()

                print(f"{created_group} has been created")
                logging.info(f"{created_group} has been created")
                return created_group
            except HttpError as create_error:
                logging.info(f"Error when creating group {email}: {create_error}")
                print(f"Error when creating group {email}: {create_error}")
                return None
        else:
            logging.info(f"Error when retrieving group {email}: {e}")
            print(f"Error when retrieving group {email}: {e}")
            return None
        
def get_group_members(service, group_email):
    try:
        # function to get al the members of a specific google group
        members = service.members().list(groupKey=group_email).execute()
        return [member['email'] for member in members.get('members', [])]
    except Exception as e:
        logging.info(f"Error when retrieving the members of {group_email}: {e}")
        print(f"Error when retrieving the members of {group_email}: {e}")
        return []

def generate_email_variations(email):
    variations = set()
    parts = email.split('@')
    local_part = parts[0]
    domain_part = parts[1]

    def generate_variations_with_dots(part):
        result = [part[:i] + "." + part[i:] for i in range(len(part))]
        return result

    def generate_variations_with_two_dots(part):
        result = [part[:i] + "." + part[i:j] + "." + part[j:] for i in range(len(part) - 1) for j in range(i + 1, len(part))]
        return result

    local_part_variations = generate_variations_with_dots(local_part) + generate_variations_with_two_dots(local_part)

    for variation in local_part_variations:
        variations.add(f"{variation}@{domain_part}")
        variations.add(f"{variation}@googlemail.com")

    # add variation without dots
    variation_without_dot = local_part.replace('.', '')
    variations.add(f"{variation_without_dot}@{domain_part}")
    variations.add(f"{variation_without_dot}@googlemail.com")
    variations.add(f"{local_part}@googlemail.com")

    return variations


def remove_member_from_group(service, group_email, member_email, deleted_addresses):
    # remove a member from a specific group
    try:
        service.members().delete(groupKey=group_email, memberKey=member_email).execute()
        print(f"Email address {member_email} removed from group {group_email}")
        if group_email not in deleted_addresses:
            deleted_addresses[group_email]=set()
        deleted_addresses[group_email].add(member_email)
    except Exception as e:
        logging.info(f"Error when removing {member_email} from group {group_email}: {e}")
        print(f"Error when removing {member_email} from group {group_email}: {e}")


def group_mailaddresses_by_json(data):
    # function to map all the data from the json file
    directory_group_mail_mapping = {}
    
    # loop through every record of the data.json
    for student in data:
        # in the json file there are different types, only the email addresses of the students have to be in the map
        if student.get("TYPE", "").lower() == "lln    ":
            class_code = student.get("KLASCODE", "")
            email_addresses = student.get("MAILADRESSEN", "")
            
            # Generate google group address based on the code of the class
            groepsadres = generate_google_group_address(class_code)
            
            # Put all the email addresses in lower case letters and remove whitespace
            email_addresses = [email.strip().lower() for email in email_addresses.split(',') if email.strip()]
            
            # Remove duplicates
            unique_mailadressen = list(set(email_addresses))
            
            # Add the unique mailadresses to the map
            if groepsadres not in directory_group_mail_mapping:
                directory_group_mail_mapping[groepsadres] = set()
            directory_group_mail_mapping[groepsadres].update(unique_mailadressen)
    
    return directory_group_mail_mapping



def get_google_groups(service):
    # function to get all the groups in where you have access to
    try:
        group_mapping = {}
        page_token = None

        while True:
            print("Getting groups....")
            logging.info("Getting groups....")
            response = service.groups().list(customer='my_customer', pageToken=page_token).execute()
            groups = response.get('groups', [])

            for group in groups:
                group_email = group.get('email', '')
                # Add only groups that do not end with "@yourdomain.be" because in this script we use subdomains of @yourdomain.be 
                if not group_email.endswith(f"@{domain_name}") and not group_email.endswith("@hhhbao.be") and "ouders" not in group_email:
                    members = get_group_members(service, group_email)
                    # Convert email addresses to lowercase
                    members = [member.lower() for member in members]
                    group_mapping[group_email.lower()] = members

            page_token = response.get('nextPageToken') # this token refresh is necessary if you have a larger organisation
            if not page_token:
                break  # No more pages

        return group_mapping

    except HttpError as e:
        print(f"Error when retrieving google groups (HTTP-error): {e}")
        logging.info(f"Error when retrieving google groups (HTTP-error): {e}")
        return {}
    except Exception as e:
        print(f"General error when retrieving groups: {e}")
        logging.info(f"General error when retrieving groups: {e}")
        return {}


    
def compare_and_sync_maps(directory_map, google_group_map, service,foute_mailadressen,added_addresses,deleted_addresses):
    # in theory a straight forward function to compare the google group map and the directory map but google does some weird things.
    # when adding a gmail adres to a google group, sometimes the api removes or adds dots to the first part of the email address ex. john.doe@gmail.com -> johndoe@gmail.com
    # therefore before removing or adding an email we have to check that the email address is not in the google group under a different form.
    # when a gmail mailaddress is added under a different form (with or without dots), it does not matter, because for google it does not matter. john.doe@gmail.com and johndoe@gmail.com
    # are the same mailbox for them
    # the function is not perfect yet, but it wil be made better in the future when I have more time
    for groepsadres, directory_mailadressen in directory_map.items():
        if groepsadres in google_group_map:
            google_addresses = google_group_map[groepsadres]
            addresses_to_add = set(directory_mailadressen) - set(google_addresses)
            addresses_to_remove = set(google_addresses) - set(directory_mailadressen)
            
            # Clean up mailaddresses_to_remove
            mailadressen_to_delete_from_removelist = set()
            for mailadress in addresses_to_remove:
                if mailadress.lower().endswith('@gmail.com'):
                    if mailadress.lower() in directory_mailadressen:
                        mailadressen_to_delete_from_removelist.add(mailadress)
                        print(f"{mailadress} removed from delete list")
                    else:
                        all_variations = generate_email_variations(mailadress)
                        for variation in all_variations:      
                            if variation.lower() in directory_mailadressen:
                                mailadressen_to_delete_from_removelist.add(mailadress)
                                print(f"{mailadress} removed from delete list")
                elif mailadress.lower().endswith("@googlemail.com"): # when adding a @gmail.com address, in some cases google transforms it to a @googlemail.com address (don't ask why :) )
                    parts = mailadress.split('@')
                    local_part = parts[0]
                    googlemail_to_gmail = f"{local_part}@gmail.com"
                    if googlemail_to_gmail in directory_mailadressen:
                        mailadressen_to_delete_from_removelist.add(mailadress)
                    else:
                        all_variations = generate_email_variations(mailadress)
                        for variation in all_variations:      
                            if variation.lower() in directory_mailadressen:
                                mailadressen_to_delete_from_removelist.add(mailadress)
                                print(f"{mailadress} removed from delete list")
                elif mailadress.lower().startswith("directie.") and mailadress.lower().endswith("@sgarchipel.be"):
                    mailadressen_to_delete_from_removelist.add(mailadress)
            addresses_to_remove -= mailadressen_to_delete_from_removelist

            for mailadres_to_remove in addresses_to_remove:
                remove_member_from_group(service, groepsadres, mailadres_to_remove,deleted_addresses)
            
            addresses_to_remove_from_add_list=set()
            for emailaddress in addresses_to_add:
                if emailaddress.endswith("@gmail.com"):
                    if emailaddress in google_addresses:
                        addresses_to_remove_from_add_list.add(emailaddress)
                        print(f"{emailaddress} removed from add list")
                    else:
                        all_variations=generate_email_variations(emailaddress)
                        for variation in all_variations:
                            if variation.lower() in google_addresses:
                                addresses_to_remove_from_add_list.add(emailaddress)
                                print(f"{emailaddress} removed from add list")
                elif emailaddress.lower().endswith("@googlemail.com"): # when adding a @gmail.com address, in some cases google transforms it to a @googlemail.com address (don't ask why :) )
                    parts = emailaddress.split('@')
                    local_part = parts[0]
                    googlemail_to_gmail = f"{local_part}@gmail.com"
                    if googlemail_to_gmail in google_addresses:
                        addresses_to_remove_from_add_list.add(emailaddress)
                    else:
                        all_variations=generate_email_variations(emailaddress)
                        for variation in all_variations:
                            if variation.lower() in google_addresses:
                                addresses_to_remove_from_add_list.add(emailaddress)
                                print(f"{emailaddress} removed from add list")
                
            addresses_to_add -= addresses_to_remove_from_add_list

            for mailadres_to_add in addresses_to_add:            
                add_member_to_group(service, groepsadres, mailadres_to_add,foute_mailadressen,added_addresses)
                  
            
            print(f"Sync complete for group: {groepsadres}")
            logging.info(f"Sync complete for group: {groepsadres}")
        else:
            print(f"Google group {groepsadres} not found, creating new group.")
            logging.info(f"Google group {groepsadres} not found, creating new group.")
            schoolcode = groepsadres.split('@')[1].split('.')[0].upper()

            try:
                create_google_group_if_not_exists(
                    service,
                    groepsadres,
                    f"Ouders {schoolcode} {groepsadres}",
                    f"Individuele groep om te mailen naar ouders met als groepsadres {groepsadres}",
                )
            except Exception as e:
                print(f"Error when creating Google group {groepsadres}: {e}") 
                logging.info(f"Error when creating Google group {groepsadres}: {e}")

            for mailadres_to_add in directory_mailadressen:
                try:
                    add_member_to_group(service, groepsadres, mailadres_to_add,foute_mailadressen,added_addresses)
                    print(f"email address {mailadres_to_add} added to group {groepsadres}")
                    logging.info(f"email address {mailadres_to_add} added to group {groepsadres}")
                except HttpError as e:
                    if e.resp.status == 409 and 'duplicate' in str(e):
                        existing_members = get_group_members(service, groepsadres)
                        if mailadres_to_add.lower() in existing_members:
                            print(f"Email address {mailadres_to_add} is aldready member of group {groepsadres}")
                            logging.info(f"Email address {mailadres_to_add} is aldready member of group {groepsadres}")
                        else:
                            print(f"Error when adding {mailadres_to_add} to the group {groepsadres}: {e}") 
                            logging.info(f"Error when adding {mailadres_to_add} to the group {groepsadres}: {e}")
                    else:
                        print(f"Error when adding {mailadres_to_add} to the group {groepsadres}: {e}")
                        logging.info(f"Error when adding {mailadres_to_add} to the group {groepsadres}: {e}")
    print(foute_mailadressen)
    return foute_mailadressen,added_addresses,deleted_addresses

def send_email(added_addresses, deleted_addresses, wrong_addresses):
     # Set email info
    message = ""
    
    if added_addresses:
        message += "\nAdded addresses:"
        for group_email, members in added_addresses.items():
            message += f"\nMembers added to group: {group_email}"
            for member in members:
                message += f"\n- {member}"

    else:
        message += "\nNo added addresses"

    if deleted_addresses:
        message += "\nDeleted addresses:"
        for group_email, members in deleted_addresses.items():
            message += f"\nMembers deleted from group: {group_email}"
            for member in members:
                message += f"\n- {member}"

    else:
        message += "\nNo deleted addresses"

    if wrong_addresses:
        message += "\nWrong addresses:"
        for group_email, members in wrong_addresses.items():
            message += f"\nWrong address in group: {group_email}"
            for member in members:
                message += f"\n- {member}"

    else:
        message += "\nNo wrong addresses"

    SENDER_EMAIL_LOGIN = os.getenv("SENDER_EMAIL_LOGIN")
    SENDER_EMAIL_PASSWORD = os.getenv("SENDER_EMAIL_PASSWORD")
    RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    smtp_username = SENDER_EMAIL_LOGIN
    smtp_password = SENDER_EMAIL_PASSWORD

    # Email setup
    msg = MIMEText(message)
    # Get current date in dd/mm/yyyy format
    current_date = datetime.now().strftime("%d/%m/%Y")

    # Update the subject with the current date
    msg['Subject'] = f'Archipelmailer Sync Report - {current_date}'
    msg['From'] = smtp_username
    msg['To'] = RECEIVER_EMAIL  # Replace with the recipient's email address

    try:
        # Connect to the SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)

        # Send the email
        server.sendmail(smtp_username, msg['To'], msg.as_string())
        print("Email sent successfully!")
        logging.info("Email sent successfully!")

    except Exception as e:
        print(f"Error sending email: {e}")
        logging.error(f"Error sending email: {e}")

    finally:
        # Disconnect from the SMTP server
        server.quit()

    print(message)
    logging.info(message)

# main script
def main():
    start_time=time.time()
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    logging.info(f"Script started on: {current_time}")
    try:
        service = create_directory_service()
        data = load_json_data()
        foute_mailadressen={}
        added_addresses={}
        deleted_addresses={}
        if data:
            directory_map = group_mailaddresses_by_json(data)
            google_group_map = get_google_groups(service)
            foute_mailadressen,added_addresses,deleted_addresses=compare_and_sync_maps(directory_map, google_group_map, service, foute_mailadressen,added_addresses,deleted_addresses)
        
        send_email(added_addresses, deleted_addresses, foute_mailadressen)

    except Exception as e:
        print(f"Unexpected error: {e}")
        logging.info(f"Unexpected error: {e}")
    end_time=time.time()
    elapsed_time=end_time-start_time
    delta_time=timedelta(seconds=elapsed_time)
    # Extract hours, minutes, and seconds
    hours, remainder = divmod(delta_time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Print the elapsed time in a human-readable format
    logging.info(f"Script execution time: {hours} hours, {minutes} minutes, {seconds} seconds")
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    logging.info(f"Script ended on: {current_time}")
if __name__ == "__main__":
    main()