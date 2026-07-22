# Dependency Audit Exceptions

The 0.2 release has three temporary audit exceptions in the optional layout-detection engine:

| Advisory | Package | Reason for temporary exception | Compensating control |
| --- | --- | --- | --- |
| [`PYSEC-2026-356`](https://osv.dev/vulnerability/PYSEC-2026-356) | `imgaug 0.4.0` | No fixed release exists; PaddleOCR 2.x depends on this package. | The service does not use `BackgroundAugmenter` or accept multiprocessing queue objects from users. |
| [`PYSEC-2026-1754`](https://osv.dev/vulnerability/PYSEC-2026-1754) | `paddlepaddle 2.6.2` | The fixed Paddle 3 line requires a PaddleOCR 3 API migration. | The service never invokes `IrGraph.draw`; its container runs as a non-root user. |
| [`PYSEC-2026-1756`](https://osv.dev/vulnerability/PYSEC-2026-1756) | `paddlepaddle 2.6.2` | The fixed Paddle 3 line requires a PaddleOCR 3 API migration. | The API accepts no model URL or model path; PPStructure receives only its package-defined model selection and runs as a non-root user. Operators should pre-warm the model cache and restrict runtime egress for hermetic deployments. |

All other backend and engine dependencies must pass `pip-audit` without exceptions. These exceptions apply only to `engines/layout-detection/requirements.lock`, must remain explicit in CI, and should be removed with the PaddleOCR 3 migration. Reassess them before the next minor public release or by 2026-10-01, whichever comes first.
