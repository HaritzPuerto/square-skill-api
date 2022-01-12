from typing import Dict, Union, List, Optional, Iterable
from pydantic import Field, BaseModel, validator


class PredictionOutput(BaseModel):
    output: str = Field(
        ...,
        description="The actual output of the model as string. "
        "Could be an answer for QA, an argument for AR or a label for Fact Checking.",
    )
    output_score: float = Field(..., description="The score assigned to the output.")


class PredictionDocument(BaseModel):
    index: str = Field(
        "", description="From which document store the document has been retrieved"
    )
    document_id: str = Field("", description="Id of the document in the index")
    document: str = Field(..., description="The text of the document")
    span: Optional[List[int]] = Field(
        description="Start and end character index of the span used. (optional)"
    )
    url: str = Field("", description="URL source of the document (if available)")
    source: str = Field("", description="The source of the document (if available)")
    document_score: float = Field(
        0, description="The score assigned to the document by retrieval"
    )


class Prediction(BaseModel):
    """
    A single prediction for a query.
    """

    prediction_score: float = Field(
        ...,
        description="The overall score assigned to the prediction. Up to the Skill to decide how to calculate",
    )
    prediction_output: PredictionOutput = Field(
        ..., description="The prediction output of the skill."
    )
    prediction_documents: List[PredictionDocument] = Field(
        [],
        description="A list of the documents used by the skill to derive this prediction. "
        "Empty if no documents were used",
    )


class QueryOutput(BaseModel):
    """
    The model for output that the skill returns after processing a query.
    """

    predictions: List[Prediction] = Field(
        ...,
        description="All predictions for the query. Predictions are sorted by prediction_score (descending)",
    )
    @staticmethod
    def sort_predictions_key(p):
        document_score = 1
        if isinstance(p, Prediction):
            answer_score = p.prediction_score
            if p.prediction_documents:
                document_score = getattr(p.prediction_documents[0], "document_score", 1)
        elif isinstance(p, dict):
            answer_score = p["prediction_score"]
            if p["prediction_documents"]:
                document_score = p["prediction_documents"][0].get("document_score", 1)
        else:
            raise TypeError(type(p))
        return (document_score, answer_score)


    @validator("predictions")
    def sort_predictions(cls, v):
        return sorted(v, key=cls.sort_predictions_key, reverse=True)

    @staticmethod
    def _prediction_documents_iter_from_context(
        iter_len: int, context: Union[None, str, List[str]]
    ) -> Iterable[PredictionDocument]:
        if context is None:
            # no context for all answers
            prediction_documents_iter = ([] for _ in range(iter_len))
        elif isinstance(context, str):
            # same context for all answers
            prediction_documents_iter = (
                [PredictionDocument(document=context)] for _ in range(iter_len)
            )
        elif isinstance(context, list):
            # different context for all answers
            if len(context) != iter_len:
                raise ValueError()
            prediction_documents_iter = [
                [PredictionDocument(document=c)] for c in context
            ]
        else:
            raise TypeError(type(context))

        return prediction_documents_iter

    @classmethod
    def from_sequence_classification(
        cls,
        answers: List[str],
        model_api_output: Dict,
        context: Union[None, str, List[str]] = None,
    ):
        """Constructor for QueryOutput from sequeunce classification of model api."""
        # TODO: make this work with the datastore api output to support all
        # prediction_document fields
        prediction_documents_iter = cls._prediction_documents_iter_from_context(
            iter_len=len(answers), context=context
        )

        predictions = []
        predictions_scores = model_api_output["model_outputs"]["logits"][0]
        for prediction_score, answer, prediction_documents in zip(
            predictions_scores, answers, prediction_documents_iter
        ):

            prediction_output = PredictionOutput(
                output=answer, output_score=prediction_score
            )

            prediction = Prediction(
                prediction_score=prediction_score,
                prediction_output=prediction_output,
                prediction_documents=prediction_documents,
            )
            predictions.append(prediction)

        return cls(predictions=predictions)

    @classmethod
    def from_question_answering(
        cls,
        model_api_output: Dict,
        context: Union[None, str, List[str]] = None,
        context_score: Union[None, float, List[float]] = None,
    ):
        """Constructor for QueryOutput from question answering of model api."""
        # TODO: make this work with the datastore api output to support all
        # prediction_document fields
        predictions: List[Prediction] = []
        for i, answers in enumerate(model_api_output["answers"]):
            if isinstance(context, list):
                assert isinstance(context_score, list)
                context_doc_i = context[i]
                context_score_i = context_score[i]
            else:
                context_doc_i = "" if context is None else context
                context_score_i = 1 if context is None else context_score

            for answer in answers:
                answer_str = answer["answer"]
                if not answer_str:
                    answer_str = "No answer found."
                answer_score = answer["score"]
                prediction_score = answer_score
                prediction_output = PredictionOutput(
                    output=answer_str, output_score=answer_score
                )

                # NOTE: currently only one document per answer is supported
                prediction_documents = (
                    [
                        PredictionDocument(
                            document=context_doc_i,
                            span=[answer["start"], answer["end"]],
                            score=context_score_i,
                        )
                    ]
                    if context_doc_i
                    else []
                )
                predictions.append(
                    Prediction(
                        prediction_score=prediction_score,
                        prediction_output=prediction_output,
                        prediction_documents=prediction_documents,
                    )
                )

        return cls(predictions=predictions)
