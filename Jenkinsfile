pipeline {
    agent any

    environment {
        PATH = "/Applications/Docker.app/Contents/Resources/bin:$PATH"

    }
    triggers { pollSCM ('* * * * *')}
    stages {
        stage('Build') {
            steps {
                withCredentials([file(credentialsId: 'env-file', variable: 'ENV_FILE')]) {
                    sh "cp \${ENV_FILE} .env"
                    sh "docker compose up -d"
                }
            }
        }
    }
}