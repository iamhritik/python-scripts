import boto3
import sys
import subprocess
import os
import logging
import json
import time

# Input parameters
action = sys.argv[1]  # scaleup or scaledown args
cluster_name = "eks-dev"
nodegroupNames = ["eks-dev-nodegroup-1"]
namespaces = ["monitoring", "logging", "non-prod"]
file_path = "workloads_data.json"
karpenter_provisioner = "default"
kubernetes_context_name = "non-prod-cluster"

client = boto3.client('eks',region_name="ap-south-1")
logging.basicConfig(format='%(asctime)s %(levelname)s %(process)d - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.INFO)


def execute_kubectl_command(command):
    try:
        return subprocess.check_output(command, shell=True, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing kubectl command: {e.output}")
        return None

def cluster_context_switch():
    context_switch = f"kubectl config use-context {kubernetes_context_name} && kubectl config current-context"
    current_context = execute_kubectl_command(context_switch)
    logging.info(current_context)   


def workload_scaleup():
    s3_fetch = f"aws s3 cp s3://eks-dev/workloads_data.json ."
    subprocess.run(s3_fetch, shell=True, check=True)
    with open(file_path, "r") as file:
        data = json.load(file)

    for deployment, deployment_details in data['Deployments'].items():
        for replicas, namespace in deployment_details.items():
            logging.info(f"Scaling Up Deployment: {deployment} | replicaCount: {replicas} | namespace: {namespace}")
            kcd_scale_command = f"kubectl scale deploy {deployment} --replicas {replicas} -n {namespace}"
            deploymentScale_output = execute_kubectl_command(kcd_scale_command)
            logging.info(deploymentScale_output)

    for statefulset, statefulset_details in data['Statefulsets'].items():
        for replicas, namespace in statefulset_details.items():
            logging.info(f"Scaling Up Deployment: {statefulset} | replicaCount: {replicas} | namespace: {namespace}")
            kcs_scale_command = f"kubectl scale sts {statefulset} --replicas {replicas} -n {namespace}"
            statefulsetScale_output = execute_kubectl_command(kcs_scale_command)
            logging.info(statefulsetScale_output)

def workload_scaledown():
    data = {}
    deploymentDetails = {}
    statefulesetDetails = {}

    for namespace in namespaces:
        kc_get_deploy = f"kubectl get deploy -o=jsonpath={{.items[*].metadata.name}} -n {namespace}"
        deployments = execute_kubectl_command(kc_get_deploy)
        kc_get_sts = f"kubectl get sts -o=jsonpath={{.items[*].metadata.name}} -n {namespace}"
        statefulsets = execute_kubectl_command(kc_get_sts)

        if deployments:
            # Split the output into a list of deployment names
            deploymentNames = deployments.strip().split()
            for deployment in deploymentNames:
                # Fetching each deployment replicasCount and save it in a dict to later use it at the time of scaleUp
                kcd_replicas_command = f"kubectl get deploy {deployment} -o=jsonpath='{{.spec.replicas}}' -n {namespace}"
                deploymentReplicas = execute_kubectl_command(kcd_replicas_command)

                if deploymentReplicas:
                    deploymentDetails.update({deployment: {deploymentReplicas: namespace}})

                    # Scaling down each deployment one by one
                    logging.info(f"Scaling Down Deployment: {deployment} | replicaCount: {deploymentReplicas} -> 0| namespace: {namespace}")
                    kcd_scaling_command = f"kubectl scale deploy {deployment} --replicas 0 -n {namespace}"
                    deploymentScaleDown = execute_kubectl_command(kcd_scaling_command)
                    logging.info(deploymentScaleDown)
        data.update ({"Deployments": deploymentDetails})

        if statefulsets:
            # Split the output into a list of deployment names
            statefulsetNames = statefulsets.strip().split()
            for statefulset in statefulsetNames:
                # Fetching each deployment replicasCount and save it in a dict to later use it at the time of scaleUp
                kcs_replicas_command = f"kubectl get sts {statefulset} -o=jsonpath='{{.spec.replicas}}' -n {namespace}"
                statefulsetReplicas = execute_kubectl_command(kcs_replicas_command)

                if statefulsetReplicas:
                    statefulesetDetails.update({statefulset: {statefulsetReplicas: namespace}})

                    # Scaling down each deployment one by one
                    logging.info(f"Scaling Down Statefulsets: {statefulset} | replicaCount: {statefulsetReplicas} -> 0| namespace: {namespace}")
                    kcs_scaling_command = f"kubectl scale sts {statefulset} --replicas 0 -n {namespace}"
                    statefulsetScaleDown = execute_kubectl_command(kcs_scaling_command)
                    logging.info(statefulsetScaleDown)
        data.update ({"Statefulsets": statefulesetDetails})

    # Saving deploymentDetails data in a JSON file with backup file
    if os.path.exists(file_path):
        backup_file_path = f"{file_path}.bak"
        backup_command = f"cp -f {file_path} {backup_file_path}"
        subprocess.run(backup_command, shell=True, check=True)
        with open(file_path, "w") as file:
            json.dump(data, file)
    else:
        print(f"The file '{file_path}' does not exist.")
        with open(file_path, "w") as file:
            json.dump(data, file)
        s3_backup = f"aws s3 mv {file_path} s3://eks-dev/workloads_data.json"
        subprocess.run(s3_backup, shell=True, check=True)


# EKS nodes scale Up and Down
def eks_nodes_scale(action):
    cluster_context_switch()
    if action == "scaleup":
        logging.info("Performing Scale Up Activity ------------")
        for nodegroup_name in nodegroupNames:
            logging.info(f"Scaling Up EKS Nodegroup: {nodegroup_name}")
            response = client.update_nodegroup_config(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                scalingConfig={
                    'minSize': 3,
                    'maxSize': 3,
                    'desiredSize': 3
                }
            )
            logging.info(f"Status: {response['update']['status']}")
            logging.info(f"Update: {response['update']['params']}")

        time.sleep(240)

        # Scale up karpenter deployment replicas
        kp_deploy_scaleUp = f"kubectl scale deploy karpenter --replicas 2 -n karpenter"
        kp_deploy = execute_kubectl_command(kp_deploy_scaleUp)
        logging.info(kp_deploy)
        time.sleep(120)

        # Scale up all the deployments & statefulsets of that namespace
        workload_scaleup()
        logging.info(f"EKS Scale Up Activity Completed")

    elif action == "scaledown":
        logging.info("Performing Scale Down Activity ------------")
        # Scale down all the deployments & statefulsets of that namespace to 0 replicas
        workload_scaledown()
        time.sleep(180)

        # Delete Karpenter provisioned nodes
        kp_node_deletion = f"kubectl delete nodes -l karpenter.sh/provisioner-name={karpenter_provisioner}"
        node_deleted = execute_kubectl_command(kp_node_deletion)
        logging.info(node_deleted)
        time.sleep(120)

        # Scale down karpenter deployment replicas to 0
        kp_deploy_scaleDown = f"kubectl scale deploy karpenter --replicas 0 -n karpenter"
        kp_deploy = execute_kubectl_command(kp_deploy_scaleDown)
        logging.info(kp_deploy)
        time.sleep(120)
        for nodegroup_name in nodegroupNames:
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

        logging.info(f"EKS Scale Down Activity Completed")
    else:
        logging.error("Please provide valid parameters - scaleup or scaledown")

# Calling main function - eks_nodes_scale
eks_nodes_scale(action)