pipeline {
    agent any

    environment {
        PATH = "/Applications/Docker.app/Contents/Resources/bin:$PATH"
    }

    options {
        disableConcurrentBuilds()
    }

    triggers { pollSCM ('* * * * *') }
    stages {
        stage('Build') {
                steps {
                    sh "docker compose build telegram-assistant"
                }
        }
        stage('Deploy') {
            steps {
                withCredentials([file(credentialsId: 'env-file', variable: 'ENV_FILE')]) {
                    sh 'chmod u+w .env'
                    sh 'cp "$ENV_FILE" .env'
                    sh 'chmod 600 .env'
                    sh "docker compose -p my-pipeline up -d --no-build"
                }
            }
        }
    }
}