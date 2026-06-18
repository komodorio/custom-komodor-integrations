#!/bin/bash

name="a-terrible-thing-$RANDOM"
url='http://localhost:9094/api/v2/alerts'

ns_service=${1-"sophos-cert-manager-loadtest/bank-of-hill-valley-20260130-144511/ledgerwriter"}
cluster_name=$(cut -f1 -d '/' <<< "$ns_service")
namespace_name=$(cut -f2 -d '/' <<< "$ns_service")
service_name=$(cut -f3 -d '/' <<< "$ns_service")

export TZ=UTC
if command -v gdate &> /dev/null
then
    date_cmd="gdate"
else
    date_cmd="date"
fi

echo "firing up alert ${name} for service ${service_name} in namespace ${namespace_name} on cluster ${cluster_name}"

curl -XPOST $url -H "Content-Type: application/json" -d @- <<EOF
[{
"labels": {
  "alertname": "$name",
  "service": "${service_name}",
  "namespace": "${namespace_name}",
  "cluster": "${cluster_name}",
  "severity": "warning",
  "instance": "$name.example.net",
  "notify": "email,pagerduty,komodor"
},
"annotations": {
  "summary": "High latency is high!"
},
"generatorURL": "http://prometheus.int.example.net/<generating_expression>"
}]
EOF

echo ""

echo "press enter to resolve alert"
read -r

echo "sending resolve"
curl -XPOST $url -H "Content-Type: application/json" -d @- <<EOF
[{
"status": "resolved",
"labels": {
  "alertname": "$name",
  "service": "${service_name}",
  "namespace": "${namespace_name}",
  "severity":"warning",
  "instance": "$name.example.net",
  "notify": "email,pagerduty,komodor"
},
"annotations": {
  "summary": "High latency is high!"
},
  "generatorURL": "http://prometheus.int.example.net/<generating_expression>",
  "startsAt": "$($date_cmd -d -1hour +"%FT%T.%3NZ")",
  "endsAt": "$($date_cmd -d -10mins +"%FT%T.%3NZ")"
}]
EOF

echo ""
