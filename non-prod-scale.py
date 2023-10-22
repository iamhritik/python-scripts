import boto3
import sys
import subprocess
import logging
import json
import time

# Input parameters
action = sys.argv[1]  # scaleup or scaledown args
cluster_name = "eks-dev"
nodegroup_name = "eks-dev-nodegroup-1"
namespaces = ["monitoring", "non-prod"]
file_path = "deployment_data.json"
karpenter_provisioner = "default"

client = boto3.client('eks')
logging.basicConfig(format='%(asctime)s %(levelname)s %(process)d - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.INFO, filename='non-prod-scale.log')


def execute_kubectl_command(command):
    try:
        return subprocess.check_output(command, shell=True, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing kubectl command: {e.output}")
        return None


def dp_scaleup():
    with open(file_path, "r") as file:
        deploy_data = json.load(file)

    for deployment, deployment_details in deploy_data.items():
        for replicas, namespace in deployment_details.items():
            logging.info(f"Scaling Up Deployment: {deployment} | replicaCount: {replicas} | namespace: {namespace}")
            kc_scale_command = f"kubectl scale deploy {deployment} --replicas {replicas} -n {namespace}"
            scale_output = execute_kubectl_command(kc_scale_command)
            logging.info(scale_output)


def dp_scaledown():
    deploymentDetails = {}

    for namespace in namespaces:
        kc_get_deploy = f"kubectl get deploy -o=jsonpath={{.items[*].metadata.name}} -n {namespace}"
        deployments = execute_kubectl_command(kc_get_deploy)

        if deployments:
            # Split the output into a list of deployment names
            deploymentNames = deployments.strip().split()
            for deployment in deploymentNames:
                # Fetching each deployment replicasCount and save it in a dict to later use it at the time of scaleUp
                kc_replicas_command = f"kubectl get deploy {deployment} -o=jsonpath='{{.spec.replicas}}' -n {namespace}"
                replicas = execute_kubectl_command(kc_replicas_command)

                if replicas:
                    deploymentDetails.update({deployment: {replicas: namespace}})

                    # Scaling down each deployment one by one
                    logging.info(f"Scaling Down Deployment: {deployment} | replicaCount: {replicas} -> 0| namespace: {namespace}")
                    kc_scaling_command = f"kubectl scale deploy {deployment} --replicas 0 -n {namespace}"
                    scaleDown = execute_kubectl_command(kc_scaling_command)
                    logging.info(scaleDown)

    # Saving deploymentDetails data in a JSON file with backup file
    current_time = time.strftime("%Y%m%d%H%M%S")
    backup_file_path = f"{file_path}_{current_time}.bak"
    backup_command = f"cp {file_path} {backup_file_path}"
    subprocess.run(backup_command, shell=True, check=True)
    with open(file_path, "w") as file:
        json.dump(deploymentDetails, file)


# EKS nodes scale Up and Down
def eks_nodes_scale(action):
    if action == "scaleup":
        logging.info("Performing Scale Up Activity ------------")
        logging.info(f"Scaling Up EKS Nodegroup: {nodegroup_name}")
        response = client.update_nodegroup_config(
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            scalingConfig={
                'minSize': 2,
                'maxSize': 2,
                'desiredSize': 2
            }
        )
        logging.info(f"Status: {response['update']['status']}")
        logging.info(f"Update: {response['update']['params']}")
        time.sleep(60)

        # Scale up karpenter deployment replicas
        kp_deploy_scaleUp = f"kubectl scale deploy karpenter --replicas 2 -n karpenter"
        kp_deploy = execute_kubectl_command(kp_deploy_scaleUp)
        logging.info(kp_deploy)
        time.sleep(60)

        # Scale up all the deployments of that namespace
        dp_scaleup()

    elif action == "scaledown":
        logging.info("Performing Scale Down Activity ------------")
        # Scale down all the deployments of that namespace to 0 replicas
        dp_scaledown()
        time.sleep(30)

        # Delete Karpenter provisioned nodes
        kp_node_deletion = f"kubectl delete nodes -l karpenter.sh/provisioner-name={karpenter_provisioner}"
        node_deleted = execute_kubectl_command(kp_node_deletion)
        logging.info(node_deleted)
        time.sleep(120)

        # Scale down karpenter deployment replicas to 0
        kp_deploy_scaleDown = f"kubectl scale deploy karpenter --replicas 0 -n karpenter"
        kp_deploy = execute_kubectl_command(kp_deploy_scaleDown)
        logging.info(kp_deploy)

        logging.info(f"Scaling Down EKS Nodegroup: {nodegroup_name}")
        response = client.update_nodegroup_config(
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            scalingConfig={
                'minSize': 0,
                'maxSize': 1,
                'desiredSize': 0
            }
        )
        logging.info(f"Status: {response['update']['status']}")
        logging.info(f"Update: {response['update']['params']}")
    else:
        logging.error("Please provide valid parameters - scaleup or scaledown")

# Calling main function - eks_nodes_scale
eks_nodes_scale(action)