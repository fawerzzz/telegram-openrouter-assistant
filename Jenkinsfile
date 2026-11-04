pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Validate') {
            steps {
                sh 'python3 -m compileall -q .'
                sh 'docker compose config -q'
            }
        }

        stage('Build') {
            steps {
                sh 'docker compose build telegram-assistant'
            }
        }

        stage('Deploy') {
            steps {
                withCredentials([file(credentialsId: 'env-file', variable: 'ENV_FILE')]) {
                    sh 'cp "$ENV_FILE" .env'
                    sh 'chmod 600 .env'
                    sh 'docker compose up -d --no-build'
                }
            }
        }
    }
}