from google.cloud import storage, aiplatform, functions_v1
from google.cloud.functions_v1.services.cloud_functions_service import CloudFunctionsServiceClient
from google.cloud.functions_v1.types.functions import EventTrigger, CreateFunctionRequest, CloudFunction
from google.api_core.exceptions import NotFound
from google.protobuf import descriptor_pb2 as duration
import ngrok
import glob
import random
import os 
import requests
import shutil
from flask import Flask, request


app = Flask(__name__)

ngrok.set_auth_token("Enter your ngrok token here")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "" #enter the path to your service account key

class ModelUpload:
    def __init__(self, project_id, location, bucket_name = None):
        self.project_id = project_id
        self.location = location
        self.storage_client = storage.Client()
        aiplatform.init(project = self.project_id,location = self.location)
        if(bucket_name):
            self.bucket_name = bucket_name
            self.create_bucket(self.bucket_name)
        else:
            self.bucket_name = 'cloud_project_model_storage' + ''.join([str(random.randint(1,9)) for _ in range(5)])
            self.create_bucket(self.bucket_name)
        

    def create_bucket(self,bucket_name):
        
        bucket = storage.Bucket(self.storage_client,bucket_name)
        bucket.location = self.location
        try: 
            self.storage_client.create_bucket(bucket)
            print(f"Created Bucket {self.bucket_name} in {self.location}")
        except NotFound:
            print(f"Bucket {self.bucket_name} already exists")

    def upload_model(self,local_model_path,bucket_path):  
        bucket = self.storage_client.bucket(self.bucket_name)
        blobs = list(bucket.list_blobs(prefix = bucket_path))
        if blobs:
            print(f'Model artifact already exists in {bucket_path}')
        else:
            rel_paths = glob.glob(local_model_path + '/**', recursive=True)
            for rel_path in rel_paths:
                remote_path = f'{bucket_path}/{"/".join(rel_path.split(os.sep)[1:])}'
                if os.path.isfile(rel_path):
                    blob = bucket.blob(remote_path)
                    blob.upload_from_filename(rel_path,timeout =300)
        
            print(f'The model has been uploaded in filename {bucket_path}')
            
    def deploy_model_to_vetex_ai_endpoint(self,model_display_name,model_artifact_uri):
        
        model = aiplatform.Model.upload(
            display_name = model_display_name,
            artifact_uri = f"gs://{self.bucket_name}/{model_artifact_uri.split('/')[0]}",
            serving_container_image_uri = "gcr.io/cloud-aiplatform/prediction/tf2-cpu.2-8:latest"
        )
        print(f"Model has been uploaded in vertext ai under the name of {model_display_name}")
        
        endpoint = aiplatform.Endpoint.create(display_name = "f{model_display_name}-endpoint")

        deployed_model = endpoint.deploy(
            model = model,
            deployed_model_display_name = model_display_name,
            machine_type = 'n1-standard-4',
            min_replica_count = 1,
            max_replica_count = 2
        )
        print(f"Model has been deployed to endpoint: {endpoint.resource_name}")
        
        return endpoint.resource_name




    def upload_zip_to_buket(self,souce_zip_path,trigger_bucket):
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(souce_zip_path)
        blob.upload_from_filename(souce_zip_path)
        print(f"Zip File{souce_zip_path} has been upladed to bucket {trigger_bucket}")
        return None

    def upload_cloud_function(self,function_name,source_zip,endpoint_id,ngrok_url,trigger_bucket = None,entry_point = 'handle_request'):
        if(not trigger_bucket):
            trigger_bucket = self.bucket_name
        self.upload_zip_to_buket(source_zip,trigger_bucket)

        client = CloudFunctionsServiceClient()
        parent = client.common_location_path(self.project_id, self.location)
        source_url = f"gs://{self.bucket_name}/{source_zip}" 

        cloud_function = {
            "name": f"projects/{project_id}/locations/{location}/functions/{function_name}",
            "entry_point": entry_point,
            "runtime": "python39",
            "source_archive_url": source_url,
            "event_trigger": {
                "event_type": "google.storage.object.finalize",
                "resource": f"projects/_/buckets/{trigger_bucket}"
            },
            "timeout": "540s",
            "available_memory_mb": 256,
            "environment_variables": {
                "PROJECT": "cloudcomputing-411615",
                "ENDPOINT_ID": endpoint_id,
                "ngrok_url": ngrok_url
            }
        }
        
       
        request = CreateFunctionRequest(
        location=parent,
        function=cloud_function,
        )

        operation = client.create_function(request=request)
        print("Deploying function, this may take a while...")
        response = operation.result()  
        print(f"Function {function_name} has been deployed.")
        print(f"Deployed function details: {response}")

@app.route('/', methods=['POST'])
def receive_prediction():
    # Get the JSON data from the request
    data = request.get_json()

    # Do something with the data (e.g., print it)
    print(data)

    return "OK", 200

project_id = 'cloudcomputing-411615'
location = 'us-central1'
#bucket_name = 'model_storage_2212'

local_model_path = 'Model/'
bucket_model_path = 'model' # The path in the bucket where the model will be stored

model_display_name = 'cloud_project_prediction_model'

grok = ngrok.forward(5000)

ModelUploader = ModelUpload(project_id,location)
ModelUploader.upload_model(local_model_path,bucket_model_path)
Model_Endpoint = ModelUploader.deploy_model_to_vetex_ai_endpoint(model_display_name,bucket_model_path)
endpoint_id = Model_Endpoint.split('/')[-1]
# prediction_url =  f"https://{location}-aiplatform.googleapis.com/v1/{endpoint_id}:predict"

print(" * ngrok tunnel \"{}\" -> \"http://127.0.0.1\"".format(grok.url()))
source_zip_path = shutil.make_archive('cloud_function','zip','Google_Cloud_Function/')
ModelUploader.upload_cloud_function('Preprocess_function',source_zip_path,endpoint_id,grok.url())
app.run(port=5000)


