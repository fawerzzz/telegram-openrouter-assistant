pipeline {
    agent any

    environment {
        PATH = "/Applications/Docker.app/Contents/Resources/bin:$PATH"
    }
    triggers { pollSCM ('* * * * *')}
    stages {
        stage('Build') {
            steps {
                sh 'docker compose up --build'
            }
        }
    }
}