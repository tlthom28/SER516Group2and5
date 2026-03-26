# Deployment & Operations Guide

This guide covers how to deploy RepoPulse to production, monitor it, and troubleshoot issues.

---

## Table of Contents

1. [Pre-deployment Checklist](#pre-deployment-checklist)
2. [Production Deployment](#production-deployment)
3. [Monitoring & Health Checks](#monitoring--health-checks)
4. [Scaling](#scaling)
5. [Troubleshooting](#troubleshooting)
6. [Backup & Recovery](#backup--recovery)

---

## Pre-deployment Checklist

Before deploying to production, verify:

### Hardware Requirements

- **CPU:** 2+ cores recommended
- **RAM:** 4GB minimum (8GB recommended for large repos)
- **Disk:** 20GB+ (for cloned repos and InfluxDB data)
- **Network:** Stable internet (for cloning GitHub repos)

### Software Requirements

- Docker and Docker Compose (latest)
- Git
- Curl or HTTP client (for API testing)

### Security Setup

```bash
# 1. Change default passwords in .env
GRAFANA_ADMIN_PASSWORD=your_strong_password_here
INFLUX_INIT_PASSWORD=your_strong_password_here

# 2. Use strong token
INFLUX_INIT_TOKEN=$(openssl rand -hex 32)

# 3. Enable HTTPS (if exposing to the internet)
# Use reverse proxy like Nginx with SSL cert

# 4. Restrict network access
# Only allow trusted IPs to reach port 8080, 8086, 3000
```

### Capacity Planning

**For different repo sizes:**
- **Small repos** (< 10k LOC): 1-2 workers, 2GB RAM
- **Medium repos** (10-100k LOC): 4 workers, 4GB RAM
- **Large repos** (> 100k LOC): 8+ workers, 8GB+ RAM

### Network & Ports

RepoPulse uses three ports:
- **8080** - API server
- **8086** - InfluxDB
- **3000** - Grafana

Ensure these are:
- Available (not in use)
- Open in firewall rules
- Forwarded if behind NAT

---

## Production Deployment

```bash
# 1. Clone and setup
git clone https://github.com/kperam1/RepoPulse.git
cd RepoPulse
cp .env.example .env

# 2. Edit .env with production settings
nano .env

# 3. Build and start in background
docker compose up -d

# 4. Verify all containers running
docker compose ps
```

**For larger deployments:** Increase `WORKER_POOL_SIZE` in `.env` and container resources in `docker-compose.yml`.

### Database Initialization

InfluxDB and Grafana initialize automatically on first startup:

```bash
# Check initialization status
docker compose logs influxdb | grep -i "bucket\|organization"
docker compose logs grafana | grep -i "initialized"
```

**What happens automatically:**
- InfluxDB creates org: `RepoPulseOrg`
- InfluxDB creates bucket: `repopulse_metrics`
- Grafana creates admin user from `.env`
- Grafana data source for InfluxDB is auto-configured

**If initialization fails:**
```bash
# Remove volumes and restart
docker compose down -v
docker compose up -d
```

---

## Monitoring & Health Checks

### API Health Endpoint

Check if the API is running:
```bash
curl http://localhost:8080/api/health
```

Expected response:
```json
{ "status": "healthy", "service": "RepoPulse API", "version": "1.0.0" }
```

### Database Health Endpoint

Check if InfluxDB is connected:
```bash
curl http://localhost:8080/api/health/db
```

Expected response:
```json
{ "status": "pass", "message": "Connected to InfluxDB" }
```

### Worker Pool Health

Check worker status:
```bash
curl http://localhost:8080/api/workers/health
```

Expected response:
```json
{
  "pool_size": 4,
  "active_workers": 2,
  "queued_jobs": 1,
  "processing_jobs": 2,
  "completed_jobs": 47,
  "failed_jobs": 0,
  "total_jobs": 50
}
```

### Container Logs

View logs for each service:
```bash
# API server
docker compose logs api

# InfluxDB
docker compose logs influxdb

# Grafana
docker compose logs grafana

# View last 100 lines
docker compose logs --tail=100 api

# Follow logs in real-time
docker compose logs -f api
```

### Grafana Dashboard Import

**Automatic provisioning** - Dashboards are auto-provisioned from `monitoring/dashboards/` on startup.

If dashboard doesn't appear:

1. Open Grafana: `http://localhost:3000`
2. Login with credentials from `.env`
3. Go to **Dashboards** → **Manage**
4. Click **+** → **Import**
5. Upload JSON from `monitoring/dashboards/loc-metrics.json`
6. Select InfluxDB data source
7. Click **Import**

**Available dashboards:**
- `loc-metrics.json` - Lines of code trends
- `RepoPulse - Grafana - Dashboard.json` - Overall metrics

### Metrics in Grafana

1. Open Grafana: `http://localhost:3000`
2. Login with credentials from `.env`
3. Go to **Dashboards** → **RepoPulse - Grafana - Dashboard**
4. Monitor:
   - Total LOC over time
   - Code churn trends
   - Job completion rate
   - Worker pool utilization

---

## Scaling

### Increase Worker Pool Size

Edit `docker-compose.yml`:
```yaml
environment:
  WORKER_POOL_SIZE=8  # Default is 4
```

Restart:
```bash
docker compose down
docker compose up -d
```

### Handle More Concurrent Jobs

**Current bottleneck:** Worker pool processes jobs sequentially per worker.

**To handle more jobs:**

1. Increase `WORKER_POOL_SIZE` (see above)
2. Monitor RAM usage: `docker stats`
3. If RAM maxes out, increase container memory:
   ```yaml
   services:
     api:
       mem_limit: 8g  # Increase from 4g
   ```

### Persistent Job Queue

Currently, jobs are stored in memory. For production with high availability, consider:
- **PostgreSQL:** Store job metadata, persist across restarts
- **Redis:** Fast in-memory cache with persistence

---

## Troubleshooting

### API Not Responding

```bash
# Check if container is running
docker compose ps api

# View logs
docker compose logs api

# Restart it
docker compose restart api
```

**Common causes:**
- Out of memory: Increase `mem_limit`
- Port conflict: Use `netstat -an | grep 8080`
- Network issue: Check firewall rules

### InfluxDB Connection Failed

```bash
# Check InfluxDB status
docker compose ps influxdb

# Test connection
curl -H "Authorization: Token devtoken12345" http://localhost:8086/health

# View logs
docker compose logs influxdb
```

**Common causes:**
- Token invalid: Check `.env` file
- Bucket doesn't exist: Auto-created on startup
- Storage full: Check disk space: `df -h`

### Job Hangs or Never Completes

```bash
# Check worker pool status
curl http://localhost:8080/api/workers/health

# Check if worker is stuck
docker compose logs api | grep -i "timeout\|error"
```

**Common causes:**
- Repo is too large (> 500MB)
- Clone timeout (120 seconds max)
- Network issues cloning from GitHub
- Insufficient RAM

**Fix:**
- Increase clone timeout in code
- Use local `local_path` instead of `repo_url`
- Increase worker pool size
- Increase container RAM

### High Memory Usage

```bash
# Check RAM per container
docker stats

# Identify memory leak
docker compose logs api | grep -i "memory\|out of"
```

**Common causes:**
- Too many concurrent jobs
- Repo clones not cleaned up
- InfluxDB data retention too high

**Fix:**
- Reduce `WORKER_POOL_SIZE`
- Manual cleanup: `docker system prune -a`
- Adjust retention: Edit `.env` `INFLUX_RETENTION_DAYS=30`

### Grafana Dashboards Not Loading

```bash
# Check Grafana status
docker compose ps grafana

# Verify InfluxDB is accessible from Grafana
docker compose exec grafana curl http://influxdb:8086/health

# Check dashboard provisioning
docker compose logs grafana
```

**Common causes:**
- InfluxDB not running
- Data source misconfigured
- Dashboard JSON syntax error

**Fix:**
- Ensure all containers are running
- Re-add InfluxDB data source in Grafana UI
- Validate JSON

---

## Backup & Recovery

### Backup Configuration

```bash
# Backup .env and docker-compose.yml
tar czf repopulse_backup_$(date +%Y%m%d).tar.gz .env docker-compose.yml
```

### Restore After Disaster

```bash
# Restore from backup
tar xzf repopulse_backup_YYYYMMDD.tar.gz

# Restart containers
docker compose up -d
```

### InfluxDB Data

InfluxDB data persists in `docker-compose.yml` volume. If deleted, historical metrics are lost but the system continues working.

To backup InfluxDB:
```bash
docker compose exec influxdb influx backup /backup --token devtoken12345 --org RepoPulseOrg
docker cp repopulse-influxdb:/backup ./
```

---

## Performance Tuning

### Optimize Clone Speed

- Use local `local_path` instead of `repo_url` to avoid GitHub network delays
- For very large repos, set `WORKER_POOL_SIZE` higher to parallelize

### Optimize InfluxDB

```bash
# Set retention policy in .env
INFLUX_RETENTION_DAYS=30  # Keep 30 days of metrics
```

### Optimize Grafana

- Set panel refresh intervals to 5m instead of 1m to reduce database load

---

## Maintenance Tasks

### Daily

- Monitor logs for errors: `docker compose logs | grep -i error`
- Check disk space: `df -h`
- Verify API is responding: `curl http://localhost:8080/api/health`

### Weekly

- Review job metrics in Grafana
- Check for failed jobs: Query InfluxDB for failed status
- Verify backups are working

### Monthly

- Backup InfluxDB (see Backup section)
- Review and rotate logs
- Test disaster recovery plan
- Update dependencies: `docker compose pull && docker compose up -d`

---

## Getting Help

### Support Channels

- **Issues:** GitHub Issues on the repo
- **Discussions:** GitHub Discussions

---

## Production Checklist

Before going live:

- [ ] Change all default passwords
- [ ] Set up HTTPS/SSL
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerts
- [ ] Create backup strategy
- [ ] Test disaster recovery
- [ ] Document any custom configuration
- [ ] Set up log aggregation (optional)
- [ ] Configure auto-restart policy
- [ ] Test under load

---

## Additional Resources

- [Docker Official Docs](https://docs.docker.com/)
- [InfluxDB Official Docs](https://docs.influxdata.com/)
- [Grafana Official Docs](https://grafana.com/docs/)
- [RepoPulse GitHub](https://github.com/kperam1/RepoPulse)
