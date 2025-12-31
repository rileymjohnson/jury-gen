resource "aws_sfn_state_machine" "jury_app_workflow" {
  name     = "JuryAppWorkflow-${var.environment}"
  role_arn = aws_iam_role.sfn_execution_role.arn

  definition = <<-EOF
  {
    "Comment": "Orchestrates the entire jury instruction generation process.",
    "StartAt": "StartJob",
    "States": {
      "StartJob": {
        "Type": "Task",
        "Resource": "${aws_lambda_function.job_start.arn}",
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "ResultPath": "$.job_data",
        "Next": "ProcessDocuments"
      },

      "ProcessDocuments": {
        "Type": "Parallel",
        "Next": "AssembleData",
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "ResultPath": "$.documents",
        "Branches": [
          {
            "StartAt": "StartComplaintTextract",
            "States": {
              "StartComplaintTextract": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_start.arn}",
                "InputPath": "$.job_data.files.complaint",
                "ResultPath": "$.complaint_textract",
                "Next": "WaitComplaint"
              },
              "WaitComplaint": {
                "Type": "Wait",
                "Seconds": 30,
                "Next": "CheckComplaintStatus"
              },
              "CheckComplaintStatus": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_check_status.arn}",
                "InputPath": "$.complaint_textract",
                "ResultPath": "$.complaint_textract.status",
                "Next": "IsComplaintReady"
              },
              "IsComplaintReady": {
                "Type": "Choice",
                "Choices": [
                  {
                    "Variable": "$.complaint_textract.status.Status",
                    "StringEquals": "SUCCEEDED",
                    "Next": "GetComplaintResults"
                  },
                  {
                    "Variable": "$.complaint_textract.status.Status",
                    "StringEquals": "FAILED",
                    "Next": "ComplaintBranchFail"
                  }
                ],
                "Default": "WaitComplaint"
              },
              "GetComplaintResults": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_get_results.arn}",
                "InputPath": "$.complaint_textract",
                "ResultPath": "$.complaint_chunks",
                "End": true
              },
              "ComplaintBranchFail": {
                "Type": "Fail",
                "Error": "ComplaintTextractFailed",
                "Cause": "Textract reported FAILED for complaint"
              }
            }
          },
          {
            "StartAt": "StartAnswerTextract",
            "States": {
              "StartAnswerTextract": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_start.arn}",
                "InputPath": "$.job_data.files.answer",
                "ResultPath": "$.answer_textract",
                "Next": "WaitAnswer"
              },
              "WaitAnswer": {
                "Type": "Wait",
                "Seconds": 30,
                "Next": "CheckAnswerStatus"
              },
              "CheckAnswerStatus": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_check_status.arn}",
                "InputPath": "$.answer_textract",
                "ResultPath": "$.answer_textract.status",
                "Next": "IsAnswerReady"
              },
              "IsAnswerReady": {
                "Type": "Choice",
                "Choices": [
                  {
                    "Variable": "$.answer_textract.status.Status",
                    "StringEquals": "SUCCEEDED",
                    "Next": "GetAnswerResults"
                  },
                  {
                    "Variable": "$.answer_textract.status.Status",
                    "StringEquals": "FAILED",
                    "Next": "AnswerBranchFail"
                  }
                ],
                "Default": "WaitAnswer"
              },
              "GetAnswerResults": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_get_results.arn}",
                "InputPath": "$.answer_textract",
                "ResultPath": "$.answer_chunks",
                "End": true
              },
              "AnswerBranchFail": {
                "Type": "Fail",
                "Error": "AnswerTextractFailed",
                "Cause": "Textract reported FAILED for answer"
              }
            }
          },
          {
            "StartAt": "StartWitnessTextract",
            "States": {
              "StartWitnessTextract": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_start.arn}",
                "InputPath": "$.job_data.files.witness",
                "ResultPath": "$.witness_textract",
                "Next": "WaitWitness"
              },
              "WaitWitness": {
                "Type": "Wait",
                "Seconds": 30,
                "Next": "CheckWitnessStatus"
              },
              "CheckWitnessStatus": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_check_status.arn}",
                "InputPath": "$.witness_textract",
                "ResultPath": "$.witness_textract.status",
                "Next": "IsWitnessReady"
              },
              "IsWitnessReady": {
                "Type": "Choice",
                "Choices": [
                  {
                    "Variable": "$.witness_textract.status.Status",
                    "StringEquals": "SUCCEEDED",
                    "Next": "GetWitnessResults"
                  },
                  {
                    "Variable": "$.witness_textract.status.Status",
                    "StringEquals": "FAILED",
                    "Next": "WitnessBranchFail"
                  }
                ],
                "Default": "WaitWitness"
              },
              "GetWitnessResults": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.textract_get_results.arn}",
                "InputPath": "$.witness_textract",
                "ResultPath": "$.witness_chunks",
                "End": true
              },
              "WitnessBranchFail": {
                "Type": "Fail",
                "Error": "WitnessTextractFailed",
                "Cause": "Textract reported FAILED for witness list"
              }
            }
          }
        ]
      },

      "AssembleData": {
        "Type": "Pass",
        "Parameters": {
          "jury_instruction_id.$": "$.job_data.jury_instruction_id",
          "complaint_chunks.$": "$.documents[0].complaint_chunks",
          "answer_chunks.$": "$.documents[1].answer_chunks",
          "witness_chunks.$": "$.documents[2].witness_chunks",
          "job_data.$": "$.job_data"
        },
        "Next": "ExtractCoreData"
      },

      "ExtractCoreData": {
        "Type": "Parallel",
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "ResultPath": "$.core_results",
        "Next": "AssembleCoreResults",
        "Branches": [
          {
            "StartAt": "ExtractClaims",
            "States": {
              "ExtractClaims": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.extract_legal_claims.arn}",
                "Parameters": {
                  "chunks.$": "$.complaint_chunks",
                  "claim_type": "claims"
                },
                "ResultPath": "$.claims",
                "End": true
              }
            }
          },
          {
            "StartAt": "ExtractCounterclaims",
            "States": {
              "ExtractCounterclaims": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.extract_legal_claims.arn}",
                "Parameters": {
                  "chunks.$": "$.answer_chunks",
                  "claim_type": "counterclaims"
                },
                "ResultPath": "$.counterclaims",
                "End": true
              }
            }
          },
          {
            "StartAt": "ExtractWitnesses",
            "States": {
              "ExtractWitnesses": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.extract_witnesses.arn}",
                "InputPath": "$.witness_chunks",
                "ResultPath": "$.witnesses",
                "End": true
              }
            }
          },
          {
            "StartAt": "ExtractCaseFacts",
            "States": {
              "ExtractCaseFacts": {
                "Type": "Task",
                "Resource": "${aws_lambda_function.extract_case_facts.arn}",
                "Parameters": {
                  "complaint_chunks.$": "$.complaint_chunks",
                  "answer_chunks.$": "$.answer_chunks",
                  "witness_chunks.$": "$.witness_chunks"
                },
                "ResultPath": "$.case_facts",
                "End": true
              }
            }
          }
        ]
      },

      "AssembleCoreResults": {
        "Type": "Pass",
        "Parameters": {
          "jury_instruction_id.$": "$.jury_instruction_id",
          "job_data.$": "$.job_data",
          "complaint_chunks.$": "$.complaint_chunks",
          "answer_chunks.$": "$.answer_chunks",
          "claims.$": "$.core_results[0].claims",
          "counterclaims.$": "$.core_results[1].counterclaims",
          "witnesses.$": "$.core_results[2].witnesses",
          "case_facts.$": "$.core_results[3].case_facts"
        },
        "Next": "EnrichCore"
      },

      "EnrichCore": {
        "Type": "Parallel",
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "Branches": [
          {
            "StartAt": "EnrichClaims",
            "States": {
              "EnrichClaims": {
                "Type": "Map",
                "InputPath": "$",
                "ItemsPath": "$.claims",
                "MaxConcurrency": 5,
                "Parameters": {
                  "item.$": "$$.Map.Item.Value",
                  "complaint_chunks.$": "$.complaint_chunks",
                  "answer_chunks.$": "$.answer_chunks"
                },
                "Iterator": {
                  "StartAt": "EnrichClaimItem",
                  "States": {
                    "EnrichClaimItem": {
                      "Type": "Task",
                      "Resource": "${aws_lambda_function.enrich_legal_item.arn}",
                      "Parameters": {
                        "item.$": "$.item",
                        "type": "claim",
                        "complaint_chunks.$": "$.complaint_chunks",
                        "answer_chunks.$": "$.answer_chunks"
                      },
                      "End": true
                    }
                  }
                },
                "ResultPath": "$.claims",
                "End": true
              }
            }
          },
          {
            "StartAt": "EnrichCounterclaims",
            "States": {
              "EnrichCounterclaims": {
                "Type": "Map",
                "InputPath": "$",
                "ItemsPath": "$.counterclaims",
                "MaxConcurrency": 5,
                "Parameters": {
                  "item.$": "$$.Map.Item.Value",
                  "complaint_chunks.$": "$.complaint_chunks",
                  "answer_chunks.$": "$.answer_chunks"
                },
                "Iterator": {
                  "StartAt": "EnrichCounterclaimItem",
                  "States": {
                    "EnrichCounterclaimItem": {
                      "Type": "Task",
                      "Resource": "${aws_lambda_function.enrich_legal_item.arn}",
                      "Parameters": {
                        "item.$": "$.item",
                        "type": "counterclaim",
                        "complaint_chunks.$": "$.complaint_chunks",
                        "answer_chunks.$": "$.answer_chunks"
                      },
                      "End": true
                    }
                  }
                },
                "ResultPath": "$.counterclaims",
                "End": true
              }
            }
          }
        ],
        "ResultPath": "$.enriched",
        "Next": "AssembleEnrichedResults"
      },

      "AssembleEnrichedResults": {
        "Type": "Pass",
        "Parameters": {
          "jury_instruction_id.$": "$.jury_instruction_id",
          "job_data.$": "$.job_data",
          "complaint_chunks.$": "$.complaint_chunks",
          "answer_chunks.$": "$.answer_chunks",
          "witnesses.$": "$.witnesses",
          "case_facts.$": "$.case_facts",
          "claims.$": "$.enriched[0].claims",
          "counterclaims.$": "$.enriched[1].counterclaims"
        },
        "Next": "GenerateInstructions"
      },

      "GenerateInstructions": {
        "Type": "Task",
        "Resource": "${aws_lambda_function.generate_instructions.arn}",
        "Parameters": {
          "claims.$": "$.claims",
          "counterclaims.$": "$.counterclaims",
          "case_facts.$": "$.case_facts",
          "witnesses.$": "$.witnesses",
          "config.$": "$.job_data.config"
        },
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "ResultPath": "$.instructions",
        "Next": "SaveResults"
      },

      "SaveResults": {
        "Type": "Task",
        "Resource": "${aws_lambda_function.job_save_results.arn}",
        "Catch": [
          {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "JobFailed"
          }
        ],
        "End": true
      },

      "JobFailed": {
        "Type": "Task",
        "Resource": "${aws_lambda_function.job_handle_error.arn}",
        "End": true
      }
    }
  }
  EOF

  # This makes sure the state machine definition is updated
  # if any Lambda ARNs change.
  depends_on = [
    aws_lambda_function.job_start,
    aws_lambda_function.textract_start,
    aws_lambda_function.textract_check_status,
    aws_lambda_function.textract_get_results,
    aws_lambda_function.extract_legal_claims,
    aws_lambda_function.extract_witnesses,
    aws_lambda_function.extract_case_facts,
    aws_lambda_function.enrich_legal_item,
    aws_lambda_function.generate_instructions,
    aws_lambda_function.job_save_results,
    aws_lambda_function.job_handle_error
  ]
}
