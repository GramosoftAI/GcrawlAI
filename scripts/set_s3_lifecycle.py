import os
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def set_s3_lifecycle():
    # Initialize the S3 client using existing credentials
    region = os.getenv("AWS_REGION", "ap-south-1")
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket = os.getenv("AWS_S3_BUCKET", "gramosoft")
    
    print(f"Connecting to S3 bucket '{bucket}' in region '{region}'...")
    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    # Define the Lifecycle Configuration rule to delete files under gcrawl_outputs/ after 7 days
    lifecycle_policy = {
        'Rules': [
            {
                'ID': 'DeleteGcrawlOutputsAfter7Days',
                'Status': 'Enabled',
                'Filter': {
                    'Prefix': 'gcrawl_outputs/'
                },
                'Expiration': {
                    'Days': 7
                }
            }
        ]
    }

    try:
        print("Applying Lifecycle Configuration to expire objects in 'gcrawl_outputs/' after 7 days...")
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration=lifecycle_policy
        )
        print("[SUCCESS] Successfully configured S3 Lifecycle Policy!")
    except Exception as e:
        print(f"\n[ERROR] Error setting lifecycle configuration: {e}")
        print("\nEXPLANATION:")
        print("Your S3 IAM user ('gsofts3bucket') does not have the 's3:PutLifecycleConfiguration' permission.")
        print("\nHOW TO FIX THIS:")
        print("You can configure this lifecycle rule directly in the AWS Console. Follow these steps:")
        print("1. Log in to the AWS Management Console and open the Amazon S3 Console.")
        print(f"2. Choose your bucket: '{bucket}'.")
        print("3. Go to the 'Management' tab.")
        print("4. Under 'Lifecycle rules', choose 'Create lifecycle rule'.")
        print("5. Enter a rule name: 'DeleteGcrawlOutputsAfter7Days'.")
        print("6. Choose 'Limit the scope of this rule using one or more filters'.")
        print("7. Under 'Prefix', enter: 'gcrawl_outputs/'")
        print("8. Under 'Lifecycle rule actions', select 'Expire current versions of objects'.")
        print("9. Under 'Expire current versions of objects', enter Days after object creation: '7'.")
        print("10. Choose 'Create rule'.")

if __name__ == "__main__":
    set_s3_lifecycle()
