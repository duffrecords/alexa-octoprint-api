# alexa-octoprint-api

This is an Alexa skill that allows you to control your Octoprint server. There are times when it's more convenient to just say "set the temperature to x degrees" out loud than to go get my laptop from the other room or scroll through the printer's basic UI.

## Disclaimer
I assume no responsibility for any damage or injury that results from the use of this skill. While I've set some sensible limits in the default configuration, always be aware that you're mixing automation with fairly strong motors and high temperatures and exposing an API to the outside world. Use your best judgement.

## Setup
These steps assume you are familiar with creating a basic Alexa skill with a Lambda function.
1. Create a new Lambda function and upload `lambda_function.py` to it. The script uses the `requests` and `webcolors` modules, which are not included in the Lambda runtime, so you'll need to install them in a virtual environment and package them with the function. I like to put these dependencies in a layer to keep them separate from the function's code so I can still view it in the Lambda console. See the AWS Lambda documentation on layers for more information.
2. Create an application key in Octoprint (don't use the global API key). Use a KMS key to encrypt it and give your function an appropriate IAM role to decrypt it. Store the encrypted value as the environment variable `OCTOPRINT_API_KEY` in the Lambda function.
3. Add your Octoprint server's URL to the `OCTOPRINT_ENDPOINT` environment variable in the Lambda function. Do not include the `/api` part of the URL or anything that follows it. Make sure this is accessible from outside. Always use HTTPS.
4. Add the following optional environment variables to the Lambda function, or omit them to use the defaults:
    * `BED_SIZE`: The size of your printer's bed in mm. Defaults to 235.
    * `XY_SPEED`: The speed at which the print head should move in the X/Y directions in mm/s. Defaults to 6000.
    * `Z_SPEED`: The speed at which the print head should move in the Z direction in mm/s. Defaults to 200.
    * `MAX_NOZZLE_TEMP`: The maximum temperature the nozzle can reach in degrees C. Defaults to 240.
    * `MAX_BED_TEMP`: The maximum temperature the bed can reach in degrees C. Defaults to 80.
    * `VOICE_NAME`: The name of the voice to use when speaking. If omitted, the default Alexa voice will be used.
5. Create a new Alexa skill and add the Lambda function as a handler.
6. Paste the contents of `model.json` into the Alexa skill's developer console. Adjust any wording as desired and then click the Build Model button.
7. Test your skill. For example, say "Alexa, ask Octoprint to check the printer status."

## Notes
To test the skill locally, copy the file `config.ini.example` to `config.ini` and edit it to match your 3D printer's settings.

The lights/torch on/off intents require the [WS281x LED Status](https://github.com/cp2004/OctoPrint-WS281x_LED_Status) plugin.