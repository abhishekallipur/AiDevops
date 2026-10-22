# Jenkins pipeline notes

A Jenkinsfile commonly defines stages such as checkout, build, test, package, and deploy. Use declarative pipeline syntax where possible. Do not hard-code credentials. A Jenkins agent must have the tools required by the pipeline (for example, Java and Maven). Validate the pipeline in a test job before using it for production.
