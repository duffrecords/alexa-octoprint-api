# from ask_sdk.standard import StandardSkillBuilder
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_model.services.directive import (
    SendDirectiveRequest, Header, SpeakDirective
)
from base64 import b64decode
import boto3
import json
import logging
import os
import re
import requests
import sys
from webcolors import name_to_hex

logger = logging.getLogger(__name__)
if 'AWS_EXECUTION_ENV' in os.environ:
    if os.environ.get('LOG_LEVEL', 'warning') == 'debug':
        logger.setLevel(logging.DEBUG)
    elif os.environ.get('LOG_LEVEL', 'warning') == 'info':
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)
    ENCRYPTED = os.environ['OCTOPRINT_API_KEY']
    # Decrypt code should run once and variables stored outside of the function
    # handler so that these are decrypted once per container
    OCTOPRINT_API_KEY = boto3.client('kms').decrypt(
        CiphertextBlob=b64decode(ENCRYPTED),
        EncryptionContext={'LambdaFunctionName': os.environ['AWS_LAMBDA_FUNCTION_NAME']}
    )['Plaintext'].decode('utf-8')
    OCTOPRINT_ENDPOINT = os.environ['OCTOPRINT_ENDPOINT']
    BED_SIZE = os.environ.get('BED_SIZE', '235')
    XY_SPEED = os.environ.get('XY_SPEED', '6000')
    Z_SPEED = os.environ.get('Z_SPEED', '200')
    MAX_NOZZLE_TEMP = os.environ.get('MAX_NOZZLE_TEMP', '240')
    MAX_BED_TEMP = os.environ.get('MAX_BED_TEMP', '80')
    VOICE_NAME = os.environ.get('VOICE_NAME', None)
else:
    from configparser import ConfigParser
    configparser = ConfigParser()
    if os.environ.get('PROJECT_DIR', ''):
        config_file = os.path.join(os.environ['PROJECT_DIR'], 'config.ini')
    else:
        # config_file = '../../config.ini'
        config_file = 'config.ini'
    configparser.read(config_file)
    os.environ['AWS_REGION'] = configparser.get('aws', 'aws_region')
    OCTOPRINT_API_KEY = configparser.get('octoprint', 'api_key')
    OCTOPRINT_ENDPOINT = configparser.get('octoprint', 'endpoint')
    BED_SIZE = configparser.get('octoprint', 'BED_SIZE')
    XY_SPEED = configparser.get('octoprint', 'XY_SPEED')
    Z_SPEED = configparser.get('octoprint', 'Z_SPEED')
    MAX_NOZZLE_TEMP = configparser.get('octoprint', 'MAX_NOZZLE_TEMP')
    MAX_BED_TEMP = configparser.get('octoprint', 'MAX_BED_TEMP')
    VOICE_NAME = os.environ.get('VOICE_NAME', None)
    logger.setLevel(logging.DEBUG)

sb = SkillBuilder()

pronunciations = {}


class Session():
    def __init__(self):
        self.attributes = None
        self.handler_input = None


session = Session()


@sb.global_request_interceptor()
def logging_request_interceptor(handler_input):
    logger.debug(f"Incoming request {handler_input.request_envelope}")
    session.attributes = handler_input.attributes_manager.session_attributes
    session.handler_input = handler_input


@sb.global_response_interceptor()
def logging_response_interceptor(handler_input, response):
    logger.debug(f"Response : {response}")


@sb.request_handler(can_handle_func=is_request_type("LaunchRequest"))
def launch_request_handler(handler_input):
    logger.debug('Python version: {}'.format(sys.version))
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False

    reprompt = "How can I help you?"
    speech = "Octo print awaiting your command."

    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_request_type("SessionEndedRequest"))
def session_ended_request_handler(handler_input):
    print(
        f"Reason for ending session: {handler_input.request_envelope.request.reason}")
    # persist_user_attributes(handler_input)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=is_intent_name("AMAZON.YesIntent"))
def handle_yes(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    speech = "I'm sorry, I didn't understand."
    reprompt = "What would you like to do?"
    return speak(speech, reprompt)


@sb.request_handler(can_handle_func=is_intent_name("AMAZON.NoIntent"))
def handle_no(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    if session_attr['awaiting_further_commands'] == True:
        speech = 'Goodbye.'
        return speak(speech, end_session=True)
    else:
        speech = "I'm sorry, I didn't understand."
        reprompt = "What would you like to do?"
        return speak(speech, reprompt)


@sb.request_handler(
    can_handle_func=lambda handler_input:
        is_intent_name("AMAZON.CancelIntent")(handler_input) or
        is_intent_name("AMAZON.StopIntent")(handler_input))
def cancel_and_stop_intent_handler(handler_input):
    """Single handler for Cancel and Stop Intent."""
    logger.debug('StopIntent')
    speech = 'Goodbye.'
    return speak(speech, end_session=True)


@sb.request_handler(can_handle_func=is_intent_name("AMAZON.HelpIntent"))
def handle_help(handler_input):
    """
    (QUESTION) Handles the 'help' built-in intention.

    You can provide context-specific help here by rendering templates conditional on the help referrer.
    """
    logger.debug('HelpIntent')
    session_attr = handler_input.attributes_manager.session_attributes
    speech = "I can send a command to the 3D printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("AMAZON.FallbackIntent"))
def fallback_handler(handler_input):
    """AMAZON.FallbackIntent is only available in en-US locale.
    This handler will not be triggered except in that locale,
    so it is safe to deploy on any locale.
    """
    # type: (HandlerInput) -> Response
    speech = "I didn't understand your request."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.exception_handler(can_handle_func=lambda i, e: True)
def all_exception_handler(handler_input, exception):
    """Catch all exception handler, log exception and
    respond with custom message.
    """
    # type: (HandlerInput, Exception) -> Response
    logger.error(exception, exc_info=True)

    speech = "Sorry, there was a problem. Please try again!!"
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ThankYouIntent"))
def thank_you(handler_input):
    speech = 'Goodbye.'
    return speak(speech, end_session=True)


def api_request(path, payload={}):
    url = OCTOPRINT_ENDPOINT + path
    headers = {
       'X-Api-Key': f"{OCTOPRINT_API_KEY}",
       'Content-Type': 'application/json'
    }
    result = {}
    if payload:
        try:
            logger.debug(f'POST data: {payload}')
            r = requests.post(url, headers=headers, auth=None, json=payload)
            logger.debug(r)
            if 200 <= r.status_code < 400:
                try:
                    result = r.json()
                    logger.debug(f'result: {result}')
                except Exception as e:
                    result = {}
            else:
                result = {}
                logger.error(r)
        except Exception as e:
            result = {}
            logger.error(e)
    else:
        try:
            r = requests.get(url, headers=headers, auth=None)
            result = r.json()
        except Exception as e:
            result = {}
            logger.error(e)
    return result


def get_slot(slot_name, default=''):
    slots = session.handler_input.request_envelope.request.intent.slots
    try:
        return slots[slot_name].value
    except LookupError:
        return default


@sb.request_handler(can_handle_func=is_intent_name("ConnectToPrinterIntent"))
def connect_to_printer(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/connection", payload={"command": "connect"})
    if 200 <= result.status_code < 400:
        speech = "The printer is connected."
    else:
        speech = "I was unable to connect to the printer."
    reprompt = "What else can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("DisconnectFromPrinterIntent"))
def disconnect_from_printer(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/connection", payload={"command": "disconnect"})
    if 200 <= result.status_code < 400:
        speech = "Disconnected from the printer."
    else:
        speech = "I was unable to disconnect from the printer."
    reprompt = "What else can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ReconnectToPrinterIntent"))
def reconnect_to_printer(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    reprompt = "What else can I help you with?"
    result = api_request("/api/connection", payload={"command": "disconnect"})
    if 200 <= result.status_code < 400:
        result = api_request("/api/connection", payload={"command": "connect"})
        if 200 <= result.status_code < 400:
            speech = "Successfully reconnected to the printer."
        else:
            speech = "I was unable to reconnect to the printer."
    else:
        speech = "I was unable to disconnect from the printer."
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetPrinterStatusIntent"))
def get_printer_status(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer")
    status = result.get('state', {}).get('text', None)
    if status:
        speech = f"The printer is {status}."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetBedTemperatureIntent"))
def get_bed_temperature(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/bed")
    temperature = result.get('bed', {}).get('actual', None)
    if temperature:
        speech = f"The bed is {temperature} degrees."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetToolTemperatureIntent"))
def get_tool_temperature(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/tool")
    temperature = result.get('tool0', {}).get('actual', None)
    if temperature:
        speech = f"The nozzle is {temperature} degrees."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("StartPrintJobIntent"))
def start_print_job(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job", payload={"command": "start"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Print job started"
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("StopPrintJobIntent"))
def stop_print_job(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job", payload={"command": "cancel"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Print job cancelled"
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("PausePrintJobIntent"))
def pause_print_job(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job", payload={"command": "pause"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Print job paused"
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ResumePrintJobIntent"))
def resume_print_job(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job", payload={"command": "resume"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Resuming printing"
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("SetBedTemperatureIntent"))
def set_bed_temperature(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    reprompt = "What would you like to do?"
    temp = get_slot("temperature")
    if not temp:
        speech = "Invalid temperature."
        return speak(speech, reprompt=reprompt)
    try:
        temperature = int(temp)
    except Exception as e:
        speech = f"{temperature} is not a number."
    if temperature < 0:
        speech = "It's not a refrigerator."
    elif temperature == 0:
        result = api_request("/api/printer/command", payload={"command": "M140 S0"})
        error = result.get('error', None)
        if error:
            speech = error
            logger.debug(f'error: {error}')
        else:
            speech = "Turning the printer bed heater off."
        reprompt = "Anything else?"
        session_attr['awaiting_further_commands'] = True
    elif temperature > MAX_BED_TEMP:
        speech = f"{temperature} degrees?  It's a print bed, not a frying pan."
    else:
        logger.debug(f'setting the bed temperature to {temperature}')
        result = api_request("/api/printer/bed", payload={"command": "target", "target": temperature})
        error = result.get('error', None)
        if error:
            speech = error
            logger.debug(f'error: {error}')
        else:
            if temperature == 0:
                speech = "Turning the printer bed heater off."
            else:
                speech = f"Setting the print bed to {temperature} degrees."
        reprompt = "Anything else?"
        session_attr['awaiting_further_commands'] = True
    logger.info(f'set_bed_temperature: {speech}')
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("SetToolTemperatureIntent"))
def set_tool_temperature(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    reprompt = "What would you like to do?"
    temp = get_slot("temperature")
    if not temp:
        speech = "Invalid temperature."
        return speak(speech, reprompt=reprompt)
    try:
        temperature = int(temp)
    except Exception as e:
        speech = f"{temperature} is not a number."
    if temperature < 0:
        speech = "What are you trying to do? 3D print an ice sculpture?"
    elif temperature == 0:
        result = api_request("/api/printer/command", payload={"command": "M104 S0"})
        error = result.get('error', None)
        if error:
            speech = error
        else:
            speech = "Turning the heating element off."
        reprompt = "Anything else?"
        session_attr['awaiting_further_commands'] = True
    elif temperature > MAX_NOZZLE_TEMP:
        speech = f"{temperature} degrees?  It's a print nozzle, not a soldering iron."
    else:
        result = api_request("/api/printer/tool", payload={"command": "target", "targets": {"tool0": temperature}})
        error = result.get('error', None)
        if error:
            speech = error
        else:
            if temperature == 0:
                speech = "Turning the heating element off."
            else:
                speech = f"Setting the nozzle to {temperature} degrees."
        reprompt = "Anything else?"
        session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("TurnBedOffIntent"))
def turn_bed_off(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M140 S0"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Turning the printer bed heater off."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("TurnToolOffIntent"))
def turn_tool_off(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M104 S0"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Turning the heating element off."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetPrintProgressIntent"))
def get_print_progress(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job")
    progress = result.get('progress', {}).get('completion', None)
    if progress is not None:
        percent = round(progress)
        speech = f"The print job is {percent} percent complete."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetTotalPrintTimeIntent"))
def get_total_print_time(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job")
    print_time = result.get('progress', {}).get('printTime', None)
    print_time_left = result.get('progress', {}).get('printTimeLeft', None)
    if print_time is not None:
        total = print_time + print_time_left
        if total > 3600:
            hours = int(print_time/3600)
            minutes = int(print_time/60) - hours * 60
            seconds = print_time % 60
            speech = f"The total print time is {hours} hours, {minutes} minutes, and {seconds} seconds."
        elif total > 60:
            minutes = int(print_time/60)
            seconds = print_time % 60
            speech = f"The total print time is {minutes} minutes, and {seconds} seconds."
        else:
            speech = f"The total print time is {print_time} seconds."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetPrintTimeLeftIntent"))
def get_print_time_left(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job")
    print_time = result.get('progress', {}).get('printTimeLeft', None)
    if print_time is not None:
        if print_time > 3600:
            hours = int(print_time/3600)
            minutes = int(print_time/60) - hours * 60
            seconds = print_time % 60
            speech = f"The remaining print time is {hours} hours, {minutes} minutes, and {seconds} seconds."
        elif print_time > 60:
            minutes = int(print_time/60)
            seconds = print_time % 60
            speech = f"The remaining print time is {minutes} minutes, and {seconds} seconds."
        else:
            speech = f"The remaining print time is {print_time} seconds."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("GetElapsedPrintTimeIntent"))
def get_total_print_time(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/job")
    print_time = result.get('progress', {}).get('printTime', None)
    if print_time is not None:
        if print_time > 3600:
            hours = int(print_time/3600)
            minutes = int(print_time/60) - hours * 60
            seconds = print_time % 60
            speech = f"The job has been printing for {hours} hours, {minutes} minutes, and {seconds} seconds."
        elif print_time > 60:
            minutes = int(print_time/60)
            seconds = print_time % 60
            speech = f"The job has been printing for {minutes} minutes, and {seconds} seconds."
        else:
            speech = f"The job has been printing for {print_time} seconds."
    else:
        speech = "I did not get a valid response from the printer."
    reprompt = "What can I help you with?"
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ProbeBedIntent"))
def probe_bed(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"commands": ["M155 S90", "G29", "@BEDLEVELVISUALIZER", "M155 S3"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Probing the printer bed level."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ProbeUpIntent"))
def probe_up(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M280 P0 S90"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Probe up."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ProbeDownIntent"))
def probe_down(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M280 P0 S10"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Probe down."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ProbeReleaseIntent"))
def probe_release(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M280 P0 S120"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Resetting probe alarm."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("SaveAllSettingsIntent"))
def save_all_settings(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M500"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = "Saving all settings."
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("HomeXYAxesIntent"))
def home_xy_axes(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"commands": ["G91", "G28 X0 Y0", "G90"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Setting X and Y <phoneme alphabet="ipa" ph="ˈæksiz">axes</phoneme> to the home position.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("HomeZAxisIntent"))
def home_z_axis(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"commands": ["G91", "G28 Z0", "G90"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Setting Z axis to the home position.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("HomeAllAxesIntent"))
def home_all_axes(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "G28"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Setting all <phoneme alphabet="ipa" ph="ˈæksiz">axes</phoneme> to the home position.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("MoveBedForwardIntent"))
def move_bed_forward(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"commands": ["G90", "G1 Y230"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Moving the print bed forward.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("MovePrintHeadIntent"))
def move_print_head(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    reprompt = "What would you like to do?"
    direction = get_slot("direction")
    distance = get_slot("distance")
    speed = XY_SPEED
    if not direction:
        speech = "I didn't understand that direction."
        return speak(speech, reprompt=reprompt)
    if not distance:
        speech = "I didn't understand that distance."
        return speak(speech, reprompt=reprompt)
    if 'left' in direction:
        axis = 'X'
        sign = '-'
    elif 'right' in direction:
        axis = 'X'
        sign = ''
    elif direction.startswith('forward'):
        axis = 'Y'
        sign = '-'
    elif direction.startswith('back'):
        axis = 'Y'
        sign = ''
    elif direction.startswith('up'):
        axis = 'Z'
        sign = ''
        speed = Z_SPEED
    elif direction.startswith('down'):
        axis = 'Z'
        sign = '-'
        speed = Z_SPEED
    else:
        speech = f'{direction} is not implemented at this time.'
        return speak(speech, reprompt=reprompt)
    if abs(distance) > BED_SIZE:
        speech = f'{distance} is greater than the length of the print bed.'
        return speak(speech, reprompt=reprompt)
    result = api_request("/api/printer/command", payload={"commands": ["G91", f"G1 {axis}{sign}{distance} F{speed}", "G90"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        unit = 'millimeter' if float(distance) == 1.0 else 'millimeters'
        speech = f'Moving the {axis} axis {distance} {unit}.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("ExtrudeIntent"))
def extrude(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    reprompt = "What would you like to do?"
    amount = get_slot("amount")
    if not amount:
        speech = "I didn't understand that amount."
        return speak(speech, reprompt=reprompt)
    if float(amount) <= 0.0:
        speech = "Extrusion amount must be a positive number."
        return speak(speech, reprompt=reprompt)
    if float(amount) > 50.0:
        speech = "This is not a pasta machine.  Stop wasting filament."
        return speak(speech, reprompt=reprompt)
    result = api_request("/api/printer/command", payload={"commands": ["G91", "M83", f"G1 E{amount} F300", "M82", "G90"]})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        unit = 'millimeter' if float(amount) == 1.0 else 'millimeters'
        speech = f'Extruding {amount} {unit} of filament.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("LightsOnIntent"))
def lights_on(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "@WS LIGHTS_ON"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Lights on.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("LightsOffIntent"))
def lights_off(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "@WS LIGHTS_OFF"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Lights off.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("TorchOnIntent"))
def torch_on(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "@WS TORCH_ON"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Torch on.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("TorchOffIntent"))
def torch_off(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "@WS TORCH_OFF"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Torch off.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("DisableStepperMotors"))
def disable_stepper_motors(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    result = api_request("/api/printer/command", payload={"command": "M18"})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = 'Disabling stepper motors.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


@sb.request_handler(can_handle_func=is_intent_name("SetLedColorIntent"))
def set_led_color(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['awaiting_further_commands'] = False
    color = get_slot("color")
    try:
        hex_color = name_to_hex(color.lower().replace(' ', ''))
    except ValueError:
        speech = "I didn't understand that color."
        reprompt = "What else can I help you with?"
        session_attr['awaiting_further_commands'] = True
        return speak(speech, reprompt=reprompt)
    result = api_request("/api/plugin/ws281x_led_status", payload={"command": "test_led", "color": hex_color})
    error = result.get('error', None)
    if error:
        speech = error
    else:
        speech = f'Setting the LEDs to {color}.'
    reprompt = "Anything else?"
    session_attr['awaiting_further_commands'] = True
    return speak(speech, reprompt=reprompt)


def speak(speech, reprompt='', end_session=False):
    speech = pronounce_tech_words(speech)
    if VOICE_NAME:
        speech = f'<speak><voice name="{VOICE_NAME}">{speech}</voice></speak>'
    # make sure output is enclosed in <speak> tags if it contains any other SSML tags
    if re.match(r'.*<[^>]+>.*', speech) and not speech.startswith('<speak>'):
        speech = f'<speak>{speech}</speak>'
    session.handler_input.response_builder.speak(speech)
    if reprompt:
        reprompt = pronounce_tech_words(reprompt)
        if VOICE_NAME:
            reprompt = f'<speak><voice name="{VOICE_NAME}">{reprompt}</voice></speak>'
        session.handler_input.response_builder.ask(reprompt)
    if end_session:
        session.handler_input.response_builder.set_should_end_session(True)
    return session.handler_input.response_builder.response


def pronounce_tech_words(text):
    for phrase, replacement in pronunciations.items():
        text = text.replace(phrase, f'<sub alias="{replacement}">{phrase}</sub>')
    return text


def sub_alias(text, alias):
    return f'<sub alias="{alias}">{text}</sub>'


def reduced_emphasis(text):
    return f'<emphasis level="reduced">{text}</emphasis>'

handler = sb.lambda_handler()
