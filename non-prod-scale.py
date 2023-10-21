import boto3
import sys
import subprocess
import logging
import json
import time

#input parameters
action = sys.argv[1] #scaleup or scaledown args
cluster_name = "eks-dev"
nodegroup_name = "eks-dev-nodegroup-1"
namespaces = ["monitoring", "non-prod"]
file_path = "deployment_data.json"
karpenter_provisioner = "default"


client = boto3.client('eks')
logging.basicConfig(format='%(asctime)s %(levelname)s %(process)d - %(message)s',datefmt='%d-%b-%y %H:%M:%S',level=logging.INFO,filename='non-prod-scale.log')


def dp_scaleup():
    with open(file_path, "r") as file:
        deploy_data = json.load(file)
    for deployment, deployment_details in deploy_data.items():
        for replicas,namespace in deployment_details.items():
            logging.info(f"Scaling Up Deployment: {deployment} | replicaCount: {replicas} | namespace: {namespace}")
            kc_scale_command = f"kubectl scale deploy {deployment} --replicas {replicas} -n {namespace}"
            scale_output = subprocess.check_output(kc_scale_command, shell=True, text=True)
            logging.info(scale_output)


def dp_scaledown():
    deploymentDetails = {}
    for namespace in namespaces:
        kc_get_deploy = f"kubectl get deploy -o=jsonpath={{.items[*].metadata.name}} -n {namespace}"
        deployments = subprocess.check_output(kc_get_deploy, shell=True, text=True)

        # Split the output into a list of deployment names
        deploymentNames = deployments.strip().split()
        for deployment in deploymentNames:
            #fetching each deployment replicasCount and save it in a dict to later use it at the time of scaleUp
            kc_replicas_command = f"kubectl get deploy {deployment} -o=jsonpath='{{.spec.replicas}}' -n {namespace}"
            replicas = subprocess.check_output(kc_replicas_command, shell=True, text=True)
            deploymentDetails.update({deployment: {replicas: namespace}})

            #scaling down each deployment one by one
            logging.info(f"Scaling Down Deployment: {deployment} | replicaCount: {replicas} -> 0| namespace: {namespace}")
            kc_scaling_command = f"kubectl scale deploy {deployment} --replicas 0 -n {namespace}"
            scaleDown = subprocess.check_output(kc_scaling_command, shell=True, text=True)     
            logging.info(scaleDown)
   
    #Saving deploymentDetails data in a JSON file
    with open(file_path, "w") as file:
        json.dump(deploymentDetails, file)


#eks nodes scale Up and Down
def eks_nodes_scale(action):
    if action == "scaleup":
        logging.info("Performing Scale Up Activity ------------")
        logging.info(f"Scaling Up EKS Nodegroup: {nodegroup_name}")
        response = client.update_nodegroup_config(
            clusterName = cluster_name,
            nodegroupName = nodegroup_name,
            scalingConfig={
                'minSize': 2,
                'maxSize': 2,
                'desiredSize': 2
            }
        )
        logging.info(f"Status: {response['update']['status']}")
        logging.info(f"Update: {response['update']['params']}")
        time.sleep(60)
        #scale up karpenter deployment replicas
        kp_deploy_scaleUp = f"kubectl scale deploy karpenter --replicas 2 -n karpenter"
        kp_deploy = subprocess.check_output(kp_deploy_scaleUp, shell=True, text=True)
        logging.info(kp_deploy)
        time.sleep(60)

        #scale up namespaces deployment replicas
        dp_scaleup()
    elif action == "scaledown":
        logging.info("Performing Scale Down Activity ------------")
        #scale down these namespace deployments to 0 replicas
        dp_scaledown()
        time.sleep(30)
    
        #Delete Karpenter provisioned nodes
        kp_node_deletion = f"kubectl delete nodes -l karpenter.sh/provisioner-name={karpenter_provisioner}"
        node_deleted = subprocess.check_output(kp_node_deletion, shell=True, text=True)
        logging.info(node_deleted)
        time.sleep(120)
        #Scale down karpenter deployment replicas to 0
        kp_deploy_scaleDown = f"kubectl scale deploy karpenter --replicas 0 -n karpenter"
        kp_deploy = subprocess.check_output(kp_deploy_scaleDown, shell=True, text=True)
        logging.info(kp_deploy)

        logging.info(f"Scaling Down EKS Nodegroup: {nodegroup_name}")
        response = client.update_nodegroup_config(
            clusterName = cluster_name,
            nodegroupName = nodegroup_name,
            scalingConfig={
                'minSize': 0,
                'maxSize': 1,
                'desiredSize': 0
            }
        )
        logging.info(f"Status: {response['update']['status']}")
        logging.info(f"Update: {response['update']['params']}")  
    else:
        logging.error(f"Please provide valid parameters - scaleup or scaledown")

#Calling main function - eks_nodes_scale
eks_nodes_scale(action)