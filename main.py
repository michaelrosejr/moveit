from fastapi import Request, BackgroundTasks, FastAPI
from dotenv.main import dotenv_values

from starlette.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from pycentral.base import ArubaCentralBase
import core.config_central as CENTRAL
import json
import requests
import coloredlogs, logging, sys

logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger)
formatter = coloredlogs.ColoredFormatter(fmt="%(asctime)s: %(funcName)20s() - %(message)s")
handler = logging.FileHandler('moveit-api.log')
handler.setLevel(logging.DEBUG)
handler.setFormatter(formatter)
logger.addHandler(handler)

CONFIG = dotenv_values('.env')
# with open("core/config.json", "r") as centralfile:
#     CENTRAL=json.load(centralfile)

#TODO Assume only one employee using RAP. If more than one and user is disabled, all user impacted
#TODO Matches on RAP subnets assigned to user. May not be good enough?

officesubnet = CENTRAL.officesubnet

app = FastAPI(title=CONFIG["PROJECT_NAME"])
app.add_middleware(CORSMiddleware, allow_origins=["*"])

central = ArubaCentralBase(central_info=CENTRAL.central_info,
                           ssl_verify=True)

def getDeviceSN(macaddress):
    apiPath = "/platform/device_inventory/v1/devices?sku_type=IAP"
    apiMethod = "GET"
    apiParams = {
        "limit": 20,
        "offset": 0
    }
    base_resp = central.command(apiMethod=apiMethod, 
                            apiPath=apiPath,
                            apiParams=apiParams)

    # print(f"macaddress: {macaddress}")

    for i in base_resp['msg']['devices']:
        centralmacaddress = i['macaddr'].lower().replace(':', '')
        if centralmacaddress == macaddress:
            # print(f"CentralMAC:  {centralmacaddress}, Serial Number: {i['serial']}")
            serialnumber = i['serial']
    logger.info(f"Serial number [{serialnumber}] found for mac address [{macaddress}]")
    
    return(serialnumber)

def getDeviceGroup(serial):
    apiPath = '/configuration/v1/devices/' + serial + '/group'
    apiMethod = "GET"
    apiParams = {
        "limit": 20,
        "offset": 0
    }
    base_resp = central.command(apiMethod=apiMethod, 
                            apiPath=apiPath,
                            apiParams=apiParams)
    group = base_resp['msg']['group']
    return group

def centralMoveDevice(serial, group):
    apiPath = '/configuration/v1/devices/move'
    apiMethod = "POST"
    apiParams = {}
    data = {
        "serials": [
            serial
        ],
        "group": group
    }

    base_resp = central.command(apiMethod=apiMethod, 
                            apiPath=apiPath,
                            apiParams=apiParams,
                            apiData=data)
    print(base_resp)
    return base_resp


def findDeviceMAC(username):
    url = "https://cppm.home.theroses.io/api/session"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + CENTRAL.clearpass_token['access_token'],
    }
    response = requests.get(url, headers=headers).json()
    items = response["_embedded"]["items"]
    # print(f"ITEMS: {items}")
    for i in items:
        if officesubnet in i['framedipaddress']:
            userdevice = i['calledstationid']
    logger.info(f"Device [{userdevice}] found in ClearPass for user [{username}]")

    return userdevice


def getUsername(event):
    """Parse event log from AD to get the AD username. This username is then 
    used to locate devices in use via ClearPass

    Args:
        event ([type]): None

    Returns:
        [str]: [username]
    """
    eventdata = json.loads(event.decode(encoding='UTF-8'))
    d1 = eventdata["data"].split("\r\n\r\n")
    d2 = d1[1].split("\r\n\t")
    d3 = d2[2].split("\t\t")
    username = d3[1]
    print(username)
    return username



def moveDevice(macaddress, togroup):
    print("MoveDevice MACADDRESS, TOGROUP: ", macaddress, togroup)
    devsn = getDeviceSN(macaddress)
    # print(f"serial: {devsn}")
    group = getDeviceGroup(devsn)
    # print(f"group: {group}")

    status = centralMoveDevice(devsn, togroup)
    # print(f"Status: {status}")
    logger.info(f"Request to move device [{devsn} / {macaddress}] from group [{group}] to [{togroup}]. Status: {status['msg']}")

    return [devsn, group, status]

def push_webhook(**kwargs):
    url = CENTRAL.teams_webhook
    # print("WEbhook URL: ", url)

    print("TEAMS TARGET: ", CENTRAL.moveit_api_url + "/redeploy?pregroup=" + kwargs['pregroup'])
    data = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": "Employee Terminated - Disabling device in Aruba Central",
        "sections": [{
            "activityTitle": "Employee Terminated - Disabling device in Aruba Central",
            "activitySubtitle": "Request via Active Directory / Workday / ServiceNOW",
            "activityImage": "https://siliconangle.com/files/2014/05/servicenow-icon.png",
            "facts": [{
                "name": "username",
                "value": kwargs['username']
            }, {
                "name": "Serial Number",
                "value": kwargs['serialnum']
            }, {
                "name": "MAC Address",
                "value": kwargs['macaddress']
            }, {
                "name": "Previous Group",
                "value": kwargs['pregroup']
            }, {
                "name": "Current Group",
                "value": kwargs['curgroup']
            }, {
                "name": "Device Type",
                "value": "AP-505H"
            }],
            "markdown": True
        }],
        "potentialAction": [{
            "@type": "ActionCard",
            "name": "Redeploy Device",
            "actions": [{
                "@type": "HttpPOST",
                "name": "Redeploy AP-505H",
                "target": CENTRAL.moveit_api_url + "/redeploy?pregroup=" + kwargs['pregroup'] + "&macaddress=" + kwargs['macaddress']
            }]
        }, {
            "@type": "ActionCard",
            "name": "Unsubscribe Central License",
            "actions": [{
                "@type": "HttpPOST",
                "name": "Unsubscribe License",
                "target": CENTRAL.moveit_api_url + "/unsubscribe?serial=" + kwargs['serialnum'] + "&macaddress=" + kwargs['macaddress']
            }]
        },]
    }
    headers = {
        'Content-Type': 'application/json'
        }
    
    response = requests.post(url, data=json.dumps(data), headers=headers)
    print("Webhook response: ", response.status_code, response.text)
    return {"status": response.status_code, "status-text": response.text}
    # return {"okay": "okay"}

def MoveDeviceTask(username):
    togroup = "UnusedDevices"
    # Send username to ClearPass to get devices used by user
    macaddress = findDeviceMAC(username)
    logger.info(f"Recevied MAC addres [{macaddress}] from ClearPass")
    # Move device from production group to InActive group
    devsn, group, status = moveDevice(macaddress, togroup)
    # statustext = f"Moved [{devsn}/{macaddress}] from [{group}] to [{togroup}] with a status of [{status}]"
    statustext = {
        "username": username,
        "serialnum": devsn,
        "macaddress": macaddress,
        "pregroup": group,
        "curgroup": togroup
    }
    # print("StatusText: ", statustext)
    push_webhook(**statustext)

    return {"status": "not set"}

@app.get("/deviceserial")
def _getDeviceGroup(devsn):
    """Get device group from Aruba central

    Args:
        devsn ([type]): serial number of device

    Returns:
        [type]: Returns the group the device is a member of
    """
    group = getDeviceGroup(devsn)
    return {"group": group}

@app.get("/webhook_test")
def webhook_test():
    username = "gavin"
    serialnum = "CNK5KSM0B8"
    macaddress = "204c03b26caa"
    pregroup = "Properties-Seattle"
    curgroup = "UnusedDevices"
    # statustext = "Request to move device [CNK5KSM0B8 / 204c03b26caa] from group [Properties-Seattle] to [UnusedDevices] was successful"
    response = push_webhook(username=username, serialnum=serialnum, macaddress=macaddress, pregroup=pregroup, curgroup=curgroup)
    return {"statustext": response}

@app.get("/ping")
def ping():
    logger.info("Received (PING), Sent (PONG)")
    return {"ping": "pong!"}

@app.post("/adhook")
async def adhook(request: Request, background_tasks: BackgroundTasks):
    logger.info(f"New request to move device to InActive group found.")
    logger.info(f"Searching for username from AD Event Logs")
    username = getUsername(await request.body())
    logger.info(f"Username ({username}) found.")
    logger.info(f"Sending request to move all devices for username {username} to InActive Central group")
    background_tasks.add_task(MoveDeviceTask, username)
    logger.info(f"Searching for devices to decommisoin owned by [{username}]")
    return {"username": username}

@app.get("/moveDevice/{macaddress}")
async def _moveDevice(macaddress: str, togroup: str):
    
    devsn, group, status = moveDevice(macaddress, togroup)

    return {"status": status['msg'], "group": togroup, "serial": devsn, "macaddress": macaddress}


@app.get("/finddevice/{username}")
async def _finddevice(username: str):
    """Find mac address of device form ClearPass using username from AD
    """
    items = findDeviceMAC(username)
    return items

@app.post("/redeploy")
async def _redeploy(pregroup: str, macaddress: str):
    """Redeploy disabled device back to previous group

    Args:
        pregroup (str): Previous group used by device before being moved to InActive group
        when user was disabled.
    """
    logger.info(f"Redeploy device [{macaddress}] requested.")

    devsn, group, status = moveDevice(macaddress, pregroup)
    logger.info(f"Redeploy of device [{macaddress}] completed successfully")

    return {"device_status": "Device " + macaddress + "moved to " + pregroup}