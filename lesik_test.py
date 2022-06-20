import urllib3
import json
import os.path
from flask import Flask, render_template, request, make_response


def get_list_from_file(file_path):
    file_exists = os.path.exists(file_path)
    if not file_exists:
        return None
    f = open(os.getcwd() + "/" + file_path, 'r', encoding='utf-8')
    tmp_list = f.readlines()
    tmp_list = list(map(lambda elem: elem.replace("\n", ""), tmp_list))
    f.close()
    return tmp_list


def parse_cooking_act_dict(file_path):
    file_exists = os.path.exists(file_path)
    if not file_exists:
        return None
    f = open(file_path, 'r', encoding='utf-8')
    delim = ">"
    cooking_act_dict = {}
    for line in f.readlines():
        line = line.replace("\n", "")
        if delim in line:
            sp_line = line.split(delim)
            cooking_act_dict[sp_line[0]] = sp_line[1]
        else:
            cooking_act_dict[line] = line
    f.close()
    return cooking_act_dict


def parse_act_to_tool_dict(file_path):
    file_exists = os.path.exists(file_path)
    if not file_exists:
        return None
    f = open(file_path, 'r', encoding='utf-8')
    delim = ">"
    t_delim = ","
    act_to_tool_dict = {}
    for line in f.readlines():
        line = line.replace("\n", "")
        if delim in line:
            sp_line = line.split(delim)
            act_to_tool_dict[sp_line[0]] = sp_line[1].split(t_delim)
    f.close()
    return act_to_tool_dict


def extract_ingredient_from_node(ingredient_type_list, volume_type_list, node):
    volume_node = None
    ingredient_list = []
    for ne in node['NE']:
        if ne['type'] in volume_type_list:
            volume_node = ne
        if ne['type'] in ingredient_type_list:
            if volume_node is not None and ne['begin'] < volume_node['end']:
                continue
            ingredient_list.append(ne)

    for word in node['word']:
        for volume in volume_list:
            if volume in word['text']:
                volume_node = word

    sub_ingredient_dict = {}
    if volume_node is not None:
        sub_ingredient_dict = {ne['text']: volume_node['text'] for ne in ingredient_list}

    return sub_ingredient_dict


def verify_pre_treated_ingredients(ingredient, pre_treated_ingredient_list):
    return ingredient in pre_treated_ingredient_list


def remove_unnecessary_verb(node, seq_list):
    flag = False
    del_seq_list = []
    for morp in node['morp']:
        if morp['type'] == 'VV' and morp['lemma'] == "넣":
            flag = True
            continue

        if flag and morp['type'] == 'EC':
            morp_id = morp['id']
            for i in range(1, len(seq_list)):
                if seq_list[i] is not None and seq_list[i]['start_id'] <= morp_id <= seq_list[i]['end_id']:
                    merge_dictionary(seq_list[i-1], seq_list[i])
                    del_seq_list.append(seq_list[i-1])
        flag = False

    for seq in del_seq_list:
        seq_list.remove(seq)
    return seq_list


def merge_dictionary(src_dict, dst_dict):
    for key in src_dict.keys():
        if key in dst_dict:
            if key == 'tool' or key == 'ingre' or key == 'seasoning' or key == 'volume':
                if src_dict.get(key) != []:
                    for value in src_dict.get(key):
                        dst_dict[key].append(value)
        else:
            dst_dict[key] = src_dict[key]


def create_sequence(node, coreference_dict, ingredient_dict, ingredient_type_list):
    # 한 문장
    seq_list = []

    # 조리 동작 한줄
    prev_seq_id = -1
    for m_ele in node['morp']:
        if m_ele['type'] == 'VV':
            act = m_ele['lemma']
            act_id = m_ele['id']
            if act in cooking_act_dict:
                # 6가지 요소
                # 이걸 line에 넣을 것
                seq_dict = {'act': cooking_act_dict[act], 'tool': [], 'ingre': [], 'seasoning': [], 'volume': [],
                            'zone': "", "start_id" : prev_seq_id + 1, "end_id": act_id}

                # insert act
                # find and insert tool
                for w_ele in node['word']:
                    if w_ele['begin'] <= prev_seq_id:
                        continue
                    if w_ele['end'] > act_id:
                        break
                    for coref_key in coreference_dict.keys():
                        if coref_key in w_ele['text']:
                            coref_sub_dict = coreference_dict.get(coref_key);
                            for key in coref_sub_dict.keys():
                                seq_dict['seasoning'].append(key + "(" + coref_sub_dict.get(key) + ")")
                    for t_ele in tool_list:
                        if t_ele in w_ele['text']:
                            seq_dict['tool'].append(t_ele)
                    for s_ele in seasoning_list:
                        if s_ele in w_ele['text']:
                            seq_dict['seasoning'].append(s_ele)
                    for i_ele in ingredient_dict:
                        if i_ele in w_ele['text']:
                            seq_dict['ingre'].append(i_ele)

                if len(seq_dict['tool']) == 0 and act in act_to_tool_dict:
                    seq_dict['tool'] = act_to_tool_dict[act]

                seq_list.append(seq_dict)
                prev_seq_id = act_id

    for sequence in seq_list:
        for ne in node['NE']:
            if ne['type'] in ingredient_type_list and ne['begin'] >= sequence['start_id'] and ne['end'] < sequence['end_id']:
                if ne['text'] not in sequence['ingre']:
                    sequence['ingre'].append(ne['text'])
    return remove_unnecessary_verb(node, seq_list)


def parse_node_section(node_list):
    coreference_dict = {}
    volume_type_list = ["QT_SIZE", "QT_COUNT", "QT_OTHERS", "QT_WEIGHT", "QT_PERCENTAGE"]
    ingredient_type_list = ["CV_FOOD", "CV_DRINK", "PT_GRASS", "PT_FRUIT", "PT_OTHERS", "AM_FISH"]
    ingredient_dict = {}
    sequence_list = []
    is_ingredient = True
    sub_type = None
    for node in node_list:
        if "[" in node['text'] and "]" in node['text']:
            sub_type = node['text'][1:-1].replace(" ", "")
            if sub_type == '조리방법':
                is_ingredient = False
            else:
                coreference_dict[sub_type] = {}
            continue
        if is_ingredient:
            sub_ingredient_dict = extract_ingredient_from_node(ingredient_type_list, volume_type_list, node)
            if sub_type is not None:
                coreference_dict[sub_type].update(sub_ingredient_dict)
            ingredient_dict.update(sub_ingredient_dict)
        else:
            sequence = create_sequence(node, coreference_dict, ingredient_dict, ingredient_type_list)
            for seq_dict in sequence:
                for ingre in seq_dict['ingre']:
                    if ingre in ingredient_dict:
                        seq_dict['volume'].append(ingredient_dict.get(ingre))
                sequence_list.append(seq_dict)
    return sequence_list


def main():
    # static params
    open_api_url = "http://aiopen.etri.re.kr:8000/WiseNLU"
    access_key = "0714b8fe-21f0-44f9-b6f9-574bf3f4524a"
    analysis_code = "SRL"

    # get cooking component list & dictionary from files
    global seasoning_list, volume_list, time_list, temperature_list, cooking_act_dict, act_to_tool_dict, tool_list
    seasoning_list = get_list_from_file("labeling/seasoning.txt")
    volume_list = get_list_from_file("labeling/volume.txt")
    time_list = get_list_from_file("labeling/time.txt")
    temperature_list = get_list_from_file("labeling/temperature.txt")
    cooking_act_dict = parse_cooking_act_dict("labeling/cooking_act.txt")
    act_to_tool_dict = parse_act_to_tool_dict("labeling/act_to_tool.txt")
    tool_list = get_list_from_file("labeling/tool.txt")

    # recipe extraction
    file_path = input("레시피 파일 경로를 입력해 주세요 : ")
    f = open(file_path, 'r')
    original_recipe = str.join("\n", f.readlines())
    f.close()

    # ETRI open api
    requestJson = {
        "access_key": access_key,
        "argument": {
            "text": original_recipe,
            "analysis_code": analysis_code
        }
    }

    http = urllib3.PoolManager()
    response = http.request(
        "POST",
        open_api_url,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        body=json.dumps(requestJson)
    )

    json_object = json.loads(response.data)
    node_list = json_object.get("return_object").get("sentence")
    sequence_list = parse_node_section(node_list)
    print(str(json.dumps(sequence_list, ensure_ascii=False)))


if __name__ == "__main__":
    main()
