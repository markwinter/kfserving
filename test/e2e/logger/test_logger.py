# Copyright 2020 kubeflow.org.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from kubernetes import client

from kfserving import KFServingClient
from kfserving import constants
from kfserving import V1beta1PredictorSpec
from kfserving import V1beta1SKLearnSpec
from kfserving import V1beta1InferenceServiceSpec
from kfserving import V1beta1InferenceService
from kfserving import V1beta1LoggerSpec
from kubernetes.client import V1ResourceRequirements
from kubernetes.client import V1Container
from ..common.utils import predict
from ..common.utils import KFSERVING_TEST_NAMESPACE
import time

KFServing = KFServingClient(config_file=os.environ.get("KUBECONFIG", "~/.kube/config"))


def test_kfserving_logger():
    msg_dumper = 'message-dumper'
    predictor = V1beta1PredictorSpec(
        min_replicas=1,
        containers=[V1Container(name="kfserving-container",
                                image='gcr.io/knative-releases/knative.dev/eventing-contrib/cmd/event_display')]
    )

    isvc = V1beta1InferenceService(api_version=constants.KFSERVING_V1BETA1,
                                   kind=constants.KFSERVING_KIND,
                                   metadata=client.V1ObjectMeta(
                                        name=msg_dumper, namespace=KFSERVING_TEST_NAMESPACE),
                                   spec=V1beta1InferenceServiceSpec(predictor=predictor))

    KFServing.create(isvc)
    KFServing.wait_isvc_ready(msg_dumper, namespace=KFSERVING_TEST_NAMESPACE)

    service_name = 'isvc-logger'
    predictor = V1beta1PredictorSpec(
        min_replicas=1,
        logger=V1beta1LoggerSpec(
            mode="all",
            url="http://message-dumper."+KFSERVING_TEST_NAMESPACE+".svc.cluster.local"
        ),
        sklearn=V1beta1SKLearnSpec(
            storage_uri='gs://kfserving-samples/models/sklearn/iris',
            resources=V1ResourceRequirements(
                requests={'cpu': '100m', 'memory': '256Mi'},
                limits={'cpu': '100m', 'memory': '256Mi'}
            )
        )
    )

    isvc = V1beta1InferenceService(api_version=constants.KFSERVING_V1BETA1,
                                   kind=constants.KFSERVING_KIND,
                                   metadata=client.V1ObjectMeta(
                                       name=service_name, namespace=KFSERVING_TEST_NAMESPACE),
                                   spec=V1beta1InferenceServiceSpec(predictor=predictor))

    KFServing.create(isvc)
    try:
        KFServing.wait_isvc_ready(service_name, namespace=KFSERVING_TEST_NAMESPACE)
    except RuntimeError:
        pods = KFServing.core_api.list_namespaced_pod(KFSERVING_TEST_NAMESPACE,
                                                      label_selector='serving.kubeflow.org/inferenceservice={}'.
                                                      format(service_name))
        for pod in pods.items:
            print(pod)

    res = predict(service_name, './data/iris_input.json')
    assert(res["predictions"] == [1, 1])
    pods = KFServing.core_api.list_namespaced_pod(KFSERVING_TEST_NAMESPACE,
                                                  label_selector='serving.kubeflow.org/inferenceservice={}'.
                                                  format(msg_dumper))
    time.sleep(5)
    log = ''
    for pod in pods.items:
        log += KFServing.core_api.read_namespaced_pod_log(name=pod.metadata.name,
                                                          namespace=pod.metadata.namespace,
                                                          container="kfserving-container")
        print(log)
    assert("org.kubeflow.serving.inference.request" in log)
    assert("org.kubeflow.serving.inference.response" in log)
    KFServing.delete(service_name, KFSERVING_TEST_NAMESPACE)
    KFServing.delete(msg_dumper, KFSERVING_TEST_NAMESPACE)
