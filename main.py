import base64
import requests
from consumer_details import CONSUMER_KEY, CONSUMER_SECRET, USERNAME, PASSWORD, MASTER_USERID, CUS_ID, MASTER_PASS, USER_ID, USER_PASSWORD
from flask import Flask, request
import xmltodict
from weasyprint import HTML


app = Flask(__name__)

URL = 'https://bbfunding.my.salesforce.com'
EXTERNAL_API_URL = 'https://www.creditbureauconnection.com/capp/bbfPost.php'  # Replace with the external API URL

def generate_token():
    params = {
        "grant_type": "password",
        "client_id": CONSUMER_KEY,
        "client_secret": CONSUMER_SECRET,
        "username": USERNAME,
        "password": PASSWORD,
    }

    oauth_endpoint = '/services/oauth2/token'
    response = requests.post(URL + oauth_endpoint, params=params)

    if response.status_code != 200:
        return None, f"Error getting access token: {response.status_code} {response.text}"

    return response.json().get('access_token'), None

xml_headers = {
    'Content-type': 'Content-Type: text/xml; charset=utf-8'
}

def generate_pdf(html_content, output_path="credit_report.pdf"):
    HTML(string=html_content).write_pdf(output_path)

@app.route('/', methods=['GET', 'POST'])
def retrieve_object_metadata():
    opp_id = '006Ro00000K1fC5'
    # opp_id = request.args.get('oppId')

    if not opp_id:
        return "Missing leadId parameter", 400

    access_token, error = generate_token()
    print(f"{access_token}")

    if error:
        return error, 401

    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}

    # Retrieve lead data using Salesforce API
    response = requests.get(URL + f'/services/data/v62.0/sobjects/Opportunity/{opp_id}', headers=headers)

    if response.status_code != 200:
        return f"Error fetching Lead data: {response.status_code} {response.text}", 400

    data = response.json()

    contact_id = data.get("ContactId")

    contact_response = requests.get(URL + f'/services/data/v62.0/sobjects/Contact/{contact_id}', headers=headers)
    contact_data = contact_response.json()


    contact = {
        "first_name": contact_data.get("FirstName", ""),
        "last_name": contact_data.get("LastName", ""),
        "ssn_raw": contact_data.get("SSN__c", ""),
        "street": contact_data.get("MailingStreet", ""),
        "city": contact_data.get("MailingCity", ""),
        "state": contact_data.get("MailingStateCode", ""),
        "zip": contact_data.get("MailingPostalCode", ""),
    }

    first_name = contact['first_name']
    last_name = contact['last_name']
    ssn_raw = contact['ssn_raw']
    ssn = ssn_raw.replace("-", "")
    street = contact['street']
    city = contact['city']
    state = contact['state']
    zip = contact['zip']

    xml = f"""
    <?xml version="1.0" encoding="utf-8"?>
    <data_area>
        <header_data>
            <user_id>{USER_ID}</user_id>
            <user_pwd>{USER_PASSWORD}</user_pwd>
            <cus_id>{CUS_ID}</cus_id>
            <single_joint>0</single_joint>
            <pre_qual>1</pre_qual>
            <action>XPN</action>
        </header_data>
        <applicant_data>
            <applicant type="primary">
                <person_name>
                    <first_name>{first_name}</first_name>
                    <last_name>{last_name}</last_name>
                </person_name>
                <address_data>
                    <address type="current">
                        <line_one>{street}</line_one>
                        <city>{city}</city>
                        <state_or_province>{state}</state_or_province>
                        <postal_code>{zip}</postal_code>
                    </address>
                </address_data>
                <social>{ssn}</social>
            </applicant>
        </applicant_data>
    </data_area>
    """

    cbc_response = requests.post(EXTERNAL_API_URL, data=xml, headers=xml_headers)

    print(cbc_response.status_code)

    dict_data = xmltodict.parse(cbc_response.content)

    error = dict_data["XML_INTERFACE"]["ERROR_DESCRIPT"]

    if error:
        return f"Error Pulling Credit: {error}"

    no_hit = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["NOHIT"]


    if no_hit == "True":
        return f"No Hit. Credit Profile Frozen, Consumer Info is Incorrect or Consumer Doesn't have a Credit Score"

    try:
        score = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["SCORES"]["SCORE"]
    except KeyError:
        description = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCMESSAGES"]["ITEM_MESSAGE"]["DESCRIPTION"]
        return description

    cc_balance = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["TOTALREVOLVINGBAL"]
    rev_avail = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["AVAILABLEPERCENTAGE"]
    open_trades = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["CURRENT"]
    install_balance = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["TOTALINSTALLMENTBAL"]
    real_estate = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["TOTALREALESTATEBAL"]
    six_mo_inq = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["LAST_6MINQUIRIES"]
    past_due = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["PASTDUE"]
    amount_past_due = dict_data["XML_INTERFACE"]["CREDITREPORT"]["BUREAU_TYPE"]["CC_ATTRIB"]["CCSUMMARY"]["AMOUNTPASTDUE"]
    credit_report_html = dict_data["XML_INTERFACE"]["CREDITREPORT"]["REPORT"]

    # Generate the PDF
    pdf_path = "credit_report.pdf"
    generate_pdf(credit_report_html, pdf_path)

    # Read PDF file as bytes
    with open(pdf_path, "rb") as pdf_file:
        pdf_bytes = pdf_file.read()

    # Encode PDF to Base64
    encoded_pdf = base64.b64encode(pdf_bytes).decode('utf-8')

    content_version_data = {
        "Title": f"{first_name} {last_name} - {score} - Experian Credit Report",
        "PathOnClient": pdf_path,
        "VersionData": encoded_pdf,
        "FirstPublishLocationId": opp_id,
    }

    attach_report = requests.post(URL + f'/services/data/v62.0/sobjects/ContentVersion/', json=content_version_data,
                                  headers=headers)

    credit_data = {
        "FICO__c": score,
        "Total_Revolving_Balance__c": cc_balance,
        "Revolving_Available__c": rev_avail,
        "Open_Tradelines__c": open_trades,
        "Total_Installment_Balance__c": install_balance,
        "Real_Estate_Balance__c": real_estate,
        "Inquires_in_Last_6_Mos__c": six_mo_inq,
        "Past_Due_Accounts__c": past_due,
        "Amount_Past_Due__c": amount_past_due,
    }

    post_credit_data = requests.patch(URL + f'/services/data/v62.0/sobjects/Lead/{opp_id}', json=credit_data,
                                      headers=headers)

    return credit_report_html

if __name__ == '__main__':
    app.run(debug=True, port=5023)

