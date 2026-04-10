pipeline {
    agent any

    environment {
        INFLUX_INIT_USERNAME = 'repopulse'
        INFLUX_INIT_PASSWORD = 'repopulse_pass12345'
        INFLUX_ORG           = 'RepoPulseOrg'
        INFLUX_BUCKET        = 'repopulse_metrics'
        INFLUX_INIT_TOKEN    = 'devtoken12345'
        INFLUX_RETENTION_DAYS = '90'
        INFLUX_URL           = 'http://influxdb:8086'
        INFLUX_TOKEN         = 'devtoken12345'
        GF_ADMIN_USER        = 'admin'
        GF_ADMIN_PASSWORD    = 'admin'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Setup Environment') {
            steps {
                script {
                    echo 'Setting up environment configuration...'
                    sh '''
                        if [ ! -f .env ]; then
                            echo "Creating .env from .env.example"
                            cp .env.example .env
                            echo "✓ .env file created successfully"
                        else
                            echo "✓ .env file already exists, skipping"
                        fi
                    '''
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker compose build --no-cache'
            }
        }

        stage('Unit Tests') {
            steps {
                sh '''
                    mkdir -p reports
                    docker compose run --rm \
                        -e PYTHONPATH=/app \
                        api python -m pytest tests/ -v \
                            --junitxml=/app/reports/unit-tests.xml \
                            --cov=src --cov-branch \
                            --cov-report=term-missing \
                            --cov-report=html:/app/reports/coverage-html \
                            --cov-report=xml:/app/reports/coverage.xml \
                            --cov-fail-under=80
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/unit-tests.xml'
                }
            }
        }

        stage('Coverage Report') {
            steps {
                echo 'Publishing HTML coverage report'
                publishHTML(target: [
                    reportDir:   'reports/coverage-html',
                    reportFiles: 'index.html',
                    reportName:  'Coverage Report',
                    keepAll:     true,
                    alwaysLinkToLastBuild: true,
                    allowMissing: true
                ])
            }
        }

        stage('Service Test') {
            steps {
                sh '''
                    echo "Tearing down leftover containers from Unit Tests"
                    docker compose down --volumes --remove-orphans || true
                    docker compose -f docker-compose.ci.yml down --volumes --remove-orphans || true

                    echo "Starting containers fresh (CI compose – no host port bindings)"
                    docker compose -f docker-compose.ci.yml up -d

                    echo "Waiting for API to become healthy"
                    MAX_RETRIES=30
                    RETRY=0
                    until docker compose -f docker-compose.ci.yml exec -T api curl -sf http://localhost:8080/health > /dev/null 2>&1; do
                        RETRY=$((RETRY + 1))
                        if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
                            echo "API did not start within $MAX_RETRIES attempts"
                            docker compose -f docker-compose.ci.yml logs api
                            exit 1
                        fi
                        echo "  retry $RETRY/$MAX_RETRIES"
                        sleep 3
                    done
                    echo "API is healthy"

                    echo "Waiting for InfluxDB to be ready"
                    RETRY=0
                    until docker compose -f docker-compose.ci.yml exec -T influxdb influx ping > /dev/null 2>&1; do
                        RETRY=$((RETRY + 1))
                        if [ "$RETRY" -ge 20 ]; then
                            echo "InfluxDB did not become ready in time"
                            docker compose -f docker-compose.ci.yml logs influxdb
                            exit 1
                        fi
                        echo "  influx retry $RETRY/20"
                        sleep 2
                    done
                    echo "InfluxDB is ready"

                    echo "Running service-level tests"

                    HTTP_CODE=$(docker compose -f docker-compose.ci.yml exec -T api curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health)
                    if [ "$HTTP_CODE" != "200" ]; then
                        echo "FAIL: /health returned $HTTP_CODE"
                        exit 1
                    fi
                    echo "  PASS: GET /health -> 200"

                    HTTP_CODE=$(docker compose -f docker-compose.ci.yml exec -T api curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/docs)
                    if [ "$HTTP_CODE" != "200" ]; then
                        echo "FAIL: /docs returned $HTTP_CODE"
                        exit 1
                    fi
                    echo "  PASS: GET /docs -> 200"

                    echo "Testing POST /analyze (clone + LOC analysis) …"
                    RESPONSE=$(docker compose -f docker-compose.ci.yml exec -T api curl -s --max-time 120 -w "\nHTTP_STATUS:%{http_code}" -X POST http://localhost:8080/analyze -H "Content-Type: application/json" -d '{"repo_url":"https://github.com/pallets/markupsafe"}')
                    HTTP_CODE=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
                    BODY=$(echo "$RESPONSE" | sed "/HTTP_STATUS:[0-9]*$/d")
                    if [ "$HTTP_CODE" != "200" ]; then
                        echo "FAIL: POST /analyze returned $HTTP_CODE"
                        echo "Response body: $BODY"
                        echo ""
                        echo "=== API container logs ==="
                        docker compose -f docker-compose.ci.yml logs --tail=60 api
                        exit 1
                    fi
                    echo "  PASS: POST /analyze -> 200"

                    if ! echo "$BODY" | grep -q "total_loc"; then
                        echo "FAIL: /analyze response missing total_loc field"
                        echo "$BODY"
                        exit 1
                    fi
                    echo "  PASS: /analyze response contains total_loc"

                    echo ""
                    echo "All service tests passed!"
                '''
            }
        }
    }

    post {
        always {
            sh '''
                docker compose -f docker-compose.ci.yml down --volumes --remove-orphans || true
                docker compose down --volumes --remove-orphans || true
            '''
        }
        success {
            echo 'Pipeline completed successfully - all tests passed!'
        }
        failure {
            echo 'Pipeline FAILED - check the stage that turned red above.'
        }
    }
}
