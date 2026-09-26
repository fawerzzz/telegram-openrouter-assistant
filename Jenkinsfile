pipeline {
    agent any

    environment {
        PATH = "/Applications/Docker.app/Contents/Resources/bin:$PATH"
        DB_PASSWORD = credentials('postgres-db-password')
        DB_USER = credentials('postgres-db-user')
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