# Docker notes

A Dockerfile describes how to build an image. Use a small runtime base image when appropriate, avoid copying secrets into images, and use a non-root runtime user where practical. Confirm the application port and artifact path for the actual project before building. A generated Dockerfile must be built and tested before deployment.
