import json
from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer
from matching import models as matching_models
from django.utils import timezone
import datetime

class NewPostConsumer(WebsocketConsumer):
    def connect(self):
        self.group_name = 'new_post'

        # Join room group
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )

        self.accept()

    def disconnect(self, close_code):
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        id = text_data_json['id']
        title = text_data_json['title']
        finding = text_data_json['finding']
        pub_date = text_data_json['pub_date']
        topic = text_data_json['topic']
        nickname = text_data_json['nickname']
        startTime = text_data_json['startTime']
        endTime = text_data_json['endTime']
        postUser = text_data_json['postUser']
        tutor = text_data_json['tutor']
        reportExist = text_data_json['reportExist']

        # Send message to room group
        async_to_sync(self.channel_layer.group_send)(
            self.group_name,
            {
                'type': 'new_post',
                'id': id,
                'title': title,
                'finding': finding,
                'pub_date': pub_date,
                'topic': topic,
                'nickname': nickname,
                'startTime': startTime,
                'endTime': endTime,
                'postUser': postUser,
                'tutor': tutor,
                'reportExist': reportExist,
            }
        )

    # Receive message from room group
    def new_post(self, event):
        id = event['id']
        post = matching_models.Post.objects.get(pk=id)
        title = event['title']
        finding = event['finding']
        pub_date = str(post.pub_date)
        nickname = event['nickname']
        startTime = event['startTime']
        endTime = event['endTime']
        postUser = event['postUser']
        tutor = event['tutor']
        reportExist = event['reportExist']
        hit = event['hit']

        # Send message to WebSocket
        self.send(text_data=json.dumps({
            'type': 'new_post',
            'id': id,
            'title': title,
            'finding': finding,
            'pub_date': pub_date,
            'nickname': nickname,
            'startTime': startTime,
            'endTime': endTime,
            'postUser': postUser,
            'tutor': tutor,
            'reportExist': reportExist,
            'hit': hit,
        }))

class PostDetailConsumer(WebsocketConsumer):
    def connect(self):
        self.group_name = 'new_comment'

        # Join room group
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )

        self.accept()

    def disconnect(self, close_code):
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        post_id = text_data_json['postid']
        reply_to = text_data_json['reply_to']
        reply_content = text_data_json['reply_content']

        data={
            'type': 'new_comment',
            'id': post_id,
            'reply_to': reply_to,
            'reply_content': reply_content,
        }

        # Send message to room group
        async_to_sync(self.channel_layer.group_send)(
            self.group_name, data
        )

    # Receive message from room group
    def new_comment(self, event):
        id = event['id']
        comment = matching_models.Comment.objects.get(pk=id)
        username = comment.user.username
        db_date = comment.pub_date
        time = timezone.localtime(db_date).strftime("%-I:%M")
        am_or_pm = timezone.localtime(db_date).strftime("%p").lower()
        am_or_pm = am_or_pm[0] + '.' + am_or_pm[1] + '.'
        date = time + ' ' + am_or_pm
        profile = matching_models.Profile.objects.get(user=comment.user)

        # Send message to WebSocket
        self.send(text_data=json.dumps({
            'type': 'new_comment',
            'id': id,
            'content': comment.content,
            'username': username,
            'date': date,
            'nickname': profile.nickname,
            'reply_to': event['reply_to'],
            'reply_content': event['reply_content'],
        }))

    # Receive message from room group
    def star_comment(self, event):
        id = event['id']
        comment = matching_models.Comment.objects.get(pk=id)

        # Send message to WebSocket
        self.send(text_data=json.dumps({
            'type': 'star_comment',
            'id': id,
            'content': comment.content,
            'username': comment.user.username,
        }))

class SessionDetailConsumer(WebsocketConsumer):
    def connect(self):
        self.group_name = 'new_comment_session'

        # Join room group
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )

        self.accept()

    def disconnect(self, close_code):
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        type1 = text_data_json['type']


        data={}

        if type1 == "new_comment":
          reply_to = text_data_json['reply_to']
          reply_content = text_data_json['reply_content']

          comment_id = text_data_json['comment_id']
          data['type'] = 'new_comment'
          data['id'] = comment_id
          data['reply_to'] = reply_to
          data['reply_content'] = reply_content

          # Send message to room group
          async_to_sync(self.channel_layer.group_send)(
              self.group_name, data
          )
        elif type1 == "start_new_tutoring":
          type2 = text_data_json['type2']
          session_pk = text_data_json['session_pk']
          if type2 == "get_next_tutee":
            next_tutee_pk = text_data_json['next_tutee_pk']
            next_tutee_url = text_data_json['next_tutee_url']
            async_to_sync(self.channel_layer.group_send)(
                self.group_name,
                {
                    'type': 'get_next_tutee',
                    'next_tutee_pk': next_tutee_pk,
                    'next_tutee_url': next_tutee_url,
                    'session_pk' : session_pk,
                }
            )
          elif type2 == "letout_current_tutee":
            current_tutee_pk = text_data_json['current_tutee_pk']
            current_tutee_url = text_data_json['current_tutee_url']
            async_to_sync(self.channel_layer.group_send)(
                self.group_name,
                {
                    'type': 'letout_current_tutee',
                    'current_tutee_pk': current_tutee_pk,
                    'current_tutee_url': current_tutee_url,
                    'session_pk' : session_pk,
                }
            )
        elif type1 == "new_waiting_tutee":
          new_tutee_turn = text_data_json['new_tutee_turn']
          async_to_sync(self.channel_layer.group_send)(
              self.group_name,
              {
                  'type': 'new_waiting_tutee',
                  'new_tutee_turn': new_tutee_turn,
              }
          )
        elif type1 == "waiting_tutee_out":
          waiting_tutee_turn = text_data_json['waiting_tutee_turn']
          async_to_sync(self.channel_layer.group_send)(
              self.group_name,
              {
                  'type': 'waiting_tutee_out',
                  'waiting_tutee_turn': waiting_tutee_turn,
              }
          )


    # Receive message from room group
    def new_comment(self, event):
        id = event['id']
        comment = matching_models.Comment.objects.get(pk=id)
        username = comment.user.username
        db_date = comment.pub_date
        time = timezone.localtime(db_date).strftime("%-I:%M")
        am_or_pm = timezone.localtime(db_date).strftime("%p").lower()
        am_or_pm = am_or_pm[0] + '.' + am_or_pm[1] + '.'
        date = time + ' ' + am_or_pm
        profile = matching_models.Profile.objects.get(user=comment.user)

        # Send message to WebSocket
        self.send(text_data=json.dumps({
            'type': 'new_comment',
            'id': id,
            'content': comment.content,
            'username': username,
            'date': date,
            'nickname': profile.nickname,
            'reply_to': event['reply_to'],
            'reply_content': event['reply_content'],
        }))

    # Receive message from room group
    def star_comment(self, event):
        id = event['id']
        comment = matching_models.Comment.objects.get(pk=id)

        # Send message to WebSocket
        self.send(text_data=json.dumps({
            'type': 'star_comment',
            'id': id,
            'content': comment.content,
            'username': comment.user.username,
        }))

    def get_next_tutee(self, event):
        try:
            next_tutee_pk = event['next_tutee_pk']
            session_pk = event['session_pk']
            log = matching_models.SessionLog.objects.filter(tutor_session_id=session_pk, tutee_id=next_tutee_pk, is_waiting=True).get()
            log.start_time = datetime.datetime.now()
            log.is_waiting = False
            log.save()
            self.send(text_data=json.dumps({
                'type': 'get_next_tutee',
                'next_tutee_pk': next_tutee_pk,
                'next_tutee_nickname': log.tutee.profile.nickname,
                'session_pk': session_pk,
                'next_tutee_url': event['next_tutee_url'],
            }))
        except:
            self.send(text_data=json.dumps({
                'type': 'get_next_tutee',
                'next_tutee_pk': -1,
                'next_tutee_nickname': "error....",
                'session_pk': session_pk,
                'next_tutee_url': event['next_tutee_url'],
            }))



    def letout_current_tutee(self, event):
        try:
            current_tutee_pk = event['current_tutee_pk']
            session_pk = event['session_pk']
            log = matching_models.SessionLog.objects.get(tutor_session_id=session_pk,tutee_id=current_tutee_pk, is_waiting=False, start_time__isnull=False, fin_time__isnull=True)
            log.fin_time = datetime.datetime.now()
            log.save()

            self.send(text_data=json.dumps({
                'type': 'letout_current_tutee',
                'current_tutee_pk': current_tutee_pk,
                'current_tutee_nickname': log.tutee.profile.nickname,
                'session_pk': session_pk,
                'current_tutee_url': event['current_tutee_url'],
            }))
        except:
            self.send(text_data=json.dumps({
                'type': 'letout_current_tutee',
                'current_tutee_pk': -1,
                'current_tutee_nickname': "error....",
                'session_pk': session_pk,
                'current_tutee_url': event['current_tutee_url'],
            }))

    def new_waiting_tutee(self, event):
      new_tutee_turn = event['new_tutee_turn']

      self.send(text_data=json.dumps({
        'type': 'new_waiting_tutee',
        'new_tutee_turn': new_tutee_turn,
      }))

    def waiting_tutee_out(self, event):
      waiting_tutee_turn = event['waiting_tutee_turn']

      self.send(text_data=json.dumps({
        'type': 'waiting_tutee_out',
        'waiting_tutee_turn': waiting_tutee_turn,
      }))
