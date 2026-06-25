import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])

_IMDS = "http://169.254.169.254/latest"


async def _imds_get(path: str) -> str:
    async with httpx.AsyncClient() as client:
        tok = (
            await client.put(
                f"{_IMDS}/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
                timeout=3,
            )
        ).text
        return (
            await client.get(
                f"{_IMDS}/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": tok},
                timeout=3,
            )
        ).text


@router.post("/rotate-ip")
async def rotate_ip(background_tasks: BackgroundTasks):
    try:
        instance_id = await _imds_get("instance-id")
        region = await _imds_get("placement/region")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not reach EC2 metadata service — is this running on EC2?")

    def _stop():
        import boto3
        boto3.client("ec2", region_name=region).stop_instances(InstanceIds=[instance_id])

    background_tasks.add_task(_stop)
    return {"message": "Instance stopping — new IP will arrive via Discord once it restarts."}
