"""Official Responses API; the only production module importing the OpenAI SDK."""
import os
from time import monotonic
import json
from pydantic import BaseModel, ValidationError
from openai import (OpenAI, AuthenticationError, PermissionDeniedError, RateLimitError,
                    APITimeoutError, APIConnectionError, APIStatusError, APIResponseValidationError)
from .base import ModelRequest, ModelResponse, ModelMetadata, ModelError, ProviderErrorCategory as C


class OpenAIModelAdapter:
    def __init__(self, *, client=None):
        # Injected clients are a trusted test boundary; generated clients disable all SDK retries.
        self._client = client

    def _get_client(self, timeout):
        if self._client is not None:
            return (self._client.with_options(max_retries=0, timeout=timeout)
                    if isinstance(self._client, OpenAI) else self._client)
        key = os.environ.get("OPENAI_API_KEY")
        if not key or not key.strip():
            raise ModelError(C.CONFIGURATION)
        # Pin official endpoint; never inherit a provider redirect from OPENAI_BASE_URL.
        return OpenAI(api_key=key, base_url="https://api.openai.com/v1", max_retries=0,
                      timeout=timeout)

    def generate(self, request: ModelRequest, output_type: type[BaseModel]) -> ModelResponse:
        try:
            request = ModelRequest.model_validate(request.model_dump())
        except ValidationError:
            raise ModelError(C.INVALID_REQUEST) from None
        started = monotonic()
        owned = self._client is None
        client = None
        metadata = None
        try:
            client = self._get_client(request.timeout_seconds)
            kwargs = dict(model=request.model, instructions=request.system_instructions,
                input=[{"role": "user", "content": request.user_input}], text_format=output_type,
                max_output_tokens=request.max_output_tokens, timeout=request.timeout_seconds,
                tools=[], tool_choice="none", store=False)
            if request.reasoning_effort is not None:
                kwargs["reasoning"] = {"effort": request.reasoning_effort}
            response = client.responses.parse(**kwargs)
            usage = response.usage
            details = None if usage is None else getattr(usage, "output_tokens_details", None)
            metadata = ModelMetadata(model=response.model, provider_response_id=response.id,
                input_tokens=None if usage is None else getattr(usage, "input_tokens", None),
                output_tokens=None if usage is None else getattr(usage, "output_tokens", None),
                total_tokens=None if usage is None else getattr(usage, "total_tokens", None),
                reasoning_tokens=None if details is None else getattr(details, "reasoning_tokens", None),
                context_selection=request.context_selection, status=response.status,
                latency_ms=(monotonic() - started) * 1000)
            if any(getattr(part, "type", None) == "refusal"
                   for item in response.output for part in getattr(item, "content", ())):
                raise ModelError(C.CONTENT_REFUSAL)
            if response.status != "completed":
                raise ModelError(C.INCOMPLETE_RESPONSE)
            parsed = response.output_parsed
            if type(parsed) is not output_type:
                raise ModelError(C.MALFORMED_RESPONSE)
            output = output_type.model_validate(parsed.model_dump(mode="json"))
            return ModelResponse(parsed_output=output, metadata=metadata)
        except ModelError as failure:
            failure.metadata = metadata
            raise
        except AuthenticationError:
            raise ModelError(C.AUTHENTICATION) from None
        except PermissionDeniedError:
            raise ModelError(C.INVALID_REQUEST) from None
        except RateLimitError:
            raise ModelError(C.RATE_LIMIT) from None
        except APITimeoutError:
            raise ModelError(C.TIMEOUT) from None
        except APIConnectionError:
            raise ModelError(C.CONNECTION) from None
        except APIStatusError as failure:
            raise ModelError(C.SERVER_ERROR if failure.status_code >= 500 else C.INVALID_REQUEST) from None
        except (ValidationError, APIResponseValidationError, json.JSONDecodeError, AttributeError, TypeError):
            raise ModelError(C.MALFORMED_RESPONSE, metadata=metadata) from None
        except Exception:
            raise ModelError(C.UNKNOWN_PROVIDER_ERROR, metadata=metadata) from None
        finally:
            if owned and client is not None:
                try:
                    client.close()
                except Exception:
                    # Never expose request-bearing SDK exception text from cleanup.
                    raise ModelError(C.UNKNOWN_PROVIDER_ERROR, metadata=metadata) from None
